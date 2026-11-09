import re
from bs4 import BeautifulSoup
from .base import (
    BaseConnector,
    clean_mc_number,
    parse_safe_date,
    parse_safe_int,
)


class SaferConnector(BaseConnector):
    """
    Fallback HTML scraper for FMCSA SAFER Company Snapshot.
    Used for per-carrier real-time refresh when QCMobile key is missing or fields need enrichment.
    """

    source_name = "safer"
    SNAPSHOT_URL = "https://safer.fmcsa.dot.gov/query.asp"

    def fetch(self, identifier: str) -> dict:
        params = {
            "searchtype": "ANY",
            "query_type": "queryCarrierSnapshot",
            "query_param": "USDOT",
            "query_string": str(identifier).strip(),
        }
        resp = self.request_with_backoff("GET", self.SNAPSHOT_URL, params=params)
        return {"html": resp.text, "dot_number": str(identifier).strip()}

    def parse_snapshot_html(self, html: str, dot_fallback: str = "") -> dict:
        soup = BeautifulSoup(html or "", "lxml")
        extracted = {"dot_number": dot_fallback}

        def find_cell_after_label(label_pattern: str) -> str:
            for th in soup.find_all(["th", "td", "a"]):
                txt = th.get_text(" ", strip=True)
                if re.search(label_pattern, txt, re.IGNORECASE):
                    parent_tr = th.find_parent("tr")
                    if not parent_tr:
                        continue
                    cells = parent_tr.find_all(["th", "td"])
                    for idx, c in enumerate(cells):
                        if c == th or th in c.descendants:
                            if idx + 1 < len(cells):
                                return cells[idx + 1].get_text(" ", strip=True)
            return ""

        usdot = find_cell_after_label(r"^USDOT Number")
        if usdot:
            extracted["dot_number"] = re.sub(r"\D", "", usdot) or dot_fallback

        extracted["legal_name"] = find_cell_after_label(r"^Legal Name")
        extracted["dba_name"] = find_cell_after_label(r"^DBA Name")
        extracted["phone"] = find_cell_after_label(r"^Phone")
        extracted["power_units"] = find_cell_after_label(r"^Power Units")
        extracted["drivers"] = find_cell_after_label(r"^Drivers")
        extracted["mcs150_date"] = find_cell_after_label(r"^MCS-150 Form Date")
        extracted["operating_status"] = find_cell_after_label(r"Operating Authority Status|USDOT Status")
        extracted["mc_number"] = find_cell_after_label(r"MC/MX/FF Number")
        extracted["physical_address"] = find_cell_after_label(r"^Physical Address")
        extracted["safety_rating"] = find_cell_after_label(r"^Rating:")

        # Parse Physical Address: "1200 COMMERCE ST DALLAS, TX 75201"
        addr_raw = extracted.get("physical_address") or ""
        m = re.search(r"^(.*?)\s+([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", addr_raw)
        if m:
            extracted["address"] = m.group(1).strip()
            extracted["city"] = m.group(2).strip().title()
            extracted["state"] = m.group(3).strip().upper()
            extracted["zip_code"] = m.group(4).strip()
        else:
            extracted["address"] = addr_raw

        return extracted

    def normalize(self, raw: dict) -> dict:
        if "html" in raw and "legal_name" not in raw:
            parsed = self.parse_snapshot_html(raw.get("html", ""), raw.get("dot_number", ""))
        else:
            parsed = dict(raw)

        dot_number = str(parsed.get("dot_number") or "").strip()
        op_stat = str(parsed.get("operating_status") or "ACTIVE").upper()
        is_active = "ACTIVE" in op_stat or "AUTHORIZED" in op_stat and "NOT AUTHORIZED" not in op_stat

        safety_raw = str(parsed.get("safety_rating") or "").strip().title()
        if safety_raw not in {"Satisfactory", "Conditional", "Unsatisfactory"}:
            safety_raw = "Unrated"

        normalized = {
            "dot_number": dot_number,
            "mc_number": clean_mc_number(parsed.get("mc_number") or ""),
            "legal_name": str(parsed.get("legal_name") or f"CARRIER {dot_number}").strip(),
            "dba_name": str(parsed.get("dba_name") or "").strip(),
            "status": "Active" if is_active else "Inactive",
            "authority_status": "Active" if is_active else "Inactive",
            "mcs150_date": parse_safe_date(parsed.get("mcs150_date")),
            "power_units": parse_safe_int(parsed.get("power_units"), default=1),
            "drivers": parse_safe_int(parsed.get("drivers"), default=1),
            "address": str(parsed.get("address") or "").strip(),
            "city": str(parsed.get("city") or "").strip(),
            "state": str(parsed.get("state") or "").strip().upper(),
            "zip_code": str(parsed.get("zip_code") or "").strip(),
            "phone": str(parsed.get("phone") or "").strip(),
            "safety_rating": safety_raw,
            "raw_json": {k: v for k, v in parsed.items() if k != "html"},
        }
        return self.finalize_carrier_dict(normalized)

