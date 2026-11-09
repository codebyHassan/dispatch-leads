import logging
import re
import time
from datetime import date, datetime
import requests
from dateutil import parser as date_parser
from carriers.utils import is_valid_email, normalize_phone_e164, resolve_timezone
from sync.models import Settings

logger = logging.getLogger("sync")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "DispatchLeadFinder/1.0 (B2B US Carrier Compliance Lookup)"
)


def parse_safe_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s or s.lower() in {"none", "null", "n/a"}:
        return None
    try:
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").date()
        return date_parser.parse(s).date()
    except Exception:
        return None


def parse_safe_int(val, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        cleaned = re.sub(r"[^\d-]", "", str(val).split(".")[0])
        return int(cleaned) if cleaned else default
    except Exception:
        return default


def parse_safe_float(val, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned else default
    except Exception:
        return default


def clean_mc_number(val: str) -> str:
    if not val:
        return ""
    digits = re.sub(r"\D", "", str(val))
    return digits


class BaseConnector:
    source_name = "base"

    def __init__(self, cfg: Settings | None = None):
        self.cfg = cfg or Settings.get_solo()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        proxies = self.cfg.get_proxies()
        if proxies:
            self.session.proxies.update(proxies)

    def _sleep_delay(self):
        delay_s = max(0, self.cfg.request_delay_ms) / 1000.0
        if delay_s > 0:
            time.sleep(delay_s)

    def request_with_backoff(self, method: str, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", max(5, self.cfg.timeout_s))
        retries = 3
        backoff = 1.0
        last_exc = None
        for attempt in range(retries):
            try:
                self._sleep_delay()
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                if resp.status_code in {429, 502, 503, 504} and attempt < retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Connector %s request error (attempt %d/%d) on %s: %s",
                    self.source_name,
                    attempt + 1,
                    retries,
                    url,
                    exc,
                )
                if attempt < retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
        raise last_exc

    def finalize_carrier_dict(self, data: dict) -> dict:
        phone = str(data.get("phone") or "").strip()
        email = str(data.get("email") or "").strip()
        state = str(data.get("state") or "").strip().upper()[:2]
        zip_code = str(data.get("zip_code") or "").strip()[:10]

        data["dot_number"] = re.sub(r"\D", "", str(data.get("dot_number") or ""))
        data["mc_number"] = clean_mc_number(data.get("mc_number") or "")
        data["state"] = state
        data["zip_code"] = zip_code
        data["phone"] = phone
        data["phone_e164"] = normalize_phone_e164(phone)
        data["email"] = email
        data["email_valid"] = is_valid_email(email)
        data["timezone"] = resolve_timezone(state, zip_code)
        data["source"] = self.source_name
        return data

