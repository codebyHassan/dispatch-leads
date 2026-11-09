import re
from datetime import datetime
from zoneinfo import ZoneInfo

STATE_TIMEZONES = {
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "IN": "America/New_York",
    "KY": "America/New_York", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/New_York", "NH": "America/New_York",
    "NJ": "America/New_York", "NY": "America/New_York", "NC": "America/New_York",
    "OH": "America/New_York", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "VT": "America/New_York", "VA": "America/New_York",
    "WV": "America/New_York",
    "AL": "America/Chicago", "AR": "America/Chicago", "IL": "America/Chicago",
    "IA": "America/Chicago", "KS": "America/Chicago", "LA": "America/Chicago",
    "MN": "America/Chicago", "MS": "America/Chicago", "MO": "America/Chicago",
    "NE": "America/Chicago", "ND": "America/Chicago", "OK": "America/Chicago",
    "SD": "America/Chicago", "TN": "America/Chicago", "TX": "America/Chicago",
    "WI": "America/Chicago",
    "AZ": "America/Phoenix", "CO": "America/Denver", "ID": "America/Denver",
    "MT": "America/Denver", "NM": "America/Denver", "UT": "America/Denver",
    "WY": "America/Denver",
    "CA": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "OR": "America/Los_Angeles", "WA": "America/Los_Angeles",
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu",
}

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def normalize_phone_e164(raw_phone: str) -> str:
    """Normalize US/North American phone numbers to E.164 (+1XXXXXXXXXX)."""
    if not raw_phone:
        return ""
    digits = re.sub(r"\D", "", str(raw_phone))
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) > 10:
        return f"+{digits}"
    return ""


def is_valid_email(raw_email: str) -> bool:
    """Check if email string is well-formed and not a placeholder."""
    if not raw_email:
        return False
    cleaned = str(raw_email).strip().lower()
    if cleaned in {"none", "n/a", "na", "null", "noemail@noemail.com", "test@test.com"}:
        return False
    return bool(EMAIL_REGEX.match(cleaned))


def resolve_timezone(state: str, zip_code: str = "") -> str:
    """Resolve US IANA timezone from state and optional ZIP prefix."""
    st = (state or "").strip().upper()
    z = (zip_code or "").strip()
    if st == "TX" and z.startswith("799"):
        return "America/Denver"
    if st == "FL" and z.startswith("324") or z.startswith("325"):
        return "America/Chicago"
    return STATE_TIMEZONES.get(st, "America/Chicago")


def get_carrier_local_time_info(tz_name: str, now_utc: datetime | None = None) -> dict:
    """
    Calculate the carrier's current local time and whether it falls inside
    9:00 AM - 5:00 PM local business hours.
    """
    tz_str = tz_name or "America/Chicago"
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("America/Chicago")

    if now_utc is None:
        now_utc = datetime.now(ZoneInfo("UTC"))
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=ZoneInfo("UTC"))

    local_dt = now_utc.astimezone(tz)
    is_good_time = 9 <= local_dt.hour < 17 and local_dt.weekday() < 5
    return {
        "formatted_time": local_dt.strftime("%I:%M %p %Z"),
        "hour": local_dt.hour,
        "is_good_time": is_good_time,
        "label": "Good time to call" if is_good_time else "Outside 9AM–5PM",
        "timezone": tz_str,
    }


def format_mc_age(days: int | None) -> str:
    """Format MC age in days into human-friendly string ('45 days' or '2 yr 3 mo')."""
    if days is None or days < 0:
        return "Missing"
    if days < 120:
        return f"{days} days"
    years = days // 365
    months = (days % 365) // 30
    if years > 0 and months > 0:
        return f"{years} yr {months} mo"
    if years > 0:
        return f"{years} yr"
    return f"{max(1, days // 30)} mo"

