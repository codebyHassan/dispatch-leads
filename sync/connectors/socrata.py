from datetime import date, timedelta
import random
from .base import (
    BaseConnector,
    clean_mc_number,
    parse_safe_date,
    parse_safe_float,
    parse_safe_int,
)


class SocrataConnector(BaseConnector):
    """
    Connector for FMCSA Company Census dataset on data.transportation.gov (Socrata API).
    Dataset ID: az4n-8mr2
    """

    source_name = "socrata"
    DATASET_URL = "https://data.transportation.gov/resource/az4n-8mr2.json"

    def fetch(self, identifier: str) -> dict:
        """Fetch a single carrier record by DOT number from Socrata."""
        params = {"dot_number": str(identifier).strip(), "$limit": 1}
        headers = {}
        if self.cfg.socrata_app_token:
            headers["X-App-Token"] = self.cfg.socrata_app_token.strip()
        resp = self.request_with_backoff("GET", self.DATASET_URL, params=params, headers=headers)
        rows = resp.json()
        return rows[0] if rows else {}

    def fetch_batch(self, limit: int = 1000, offset: int = 0, state: str = "") -> list[dict]:
        """Fetch a batch of carrier census records from Socrata."""
        params = {
            "$limit": limit,
            "$offset": offset,
            "$order": "dot_number DESC",
        }
        if state:
            params["phy_state"] = state.strip().upper()
        headers = {}
        if self.cfg.socrata_app_token:
            headers["X-App-Token"] = self.cfg.socrata_app_token.strip()
        resp = self.request_with_backoff("GET", self.DATASET_URL, params=params, headers=headers)
        data = resp.json()
        return data if isinstance(data, list) else []

    def normalize(self, raw: dict) -> dict:
        """Map Socrata fields documented in docs/data_sources.md to internal CarrierDict."""
        dot_number = str(raw.get("dot_number") or "").strip()
        mc_raw = (
            raw.get("mc_mx_ff_number")
            or raw.get("docket_number")
            or raw.get("mc_number")
            or ""
        )
        status_code = str(raw.get("status_code") or "A").strip().upper()
        status = "Active" if status_code in {"A", "ACTIVE"} else "Inactive"

        auth_status_raw = str(
            raw.get("authority_status") or raw.get("common_stat") or status_code
        ).strip().upper()
        if auth_status_raw in {"A", "ACTIVE"}:
            authority_status = "Active"
        elif auth_status_raw in {"P", "PENDING"}:
            authority_status = "Pending"
        else:
            authority_status = "Inactive"

        contract_stat = str(raw.get("contract_stat") or "").strip().upper()
        authority_type = raw.get("authority_type") or (
            "Contract" if contract_stat == "A" and auth_status_raw != "A" else "Common"
        )

        op_code = str(raw.get("carrier_operation") or raw.get("operation_type") or "A").strip().upper()
        if op_code in {"A", "INTERSTATE"}:
            operation_type = "Interstate"
        elif op_code in {"B", "INTRASTATE HAZMAT"}:
            operation_type = "Intrastate Hazmat"
        elif op_code in {"C", "INTRASTATE"}:
            operation_type = "Intrastate"
        else:
            operation_type = "Interstate"

        grant_date = parse_safe_date(
            raw.get("authority_grant_date") or raw.get("add_date") or raw.get("mcs150_date")
        )
        mcs150_date = parse_safe_date(raw.get("mcs150_date"))

        safety_raw = str(raw.get("safety_rating") or "").strip().upper()
        safety_map = {
            "S": "Satisfactory",
            "SATISFACTORY": "Satisfactory",
            "C": "Conditional",
            "CONDITIONAL": "Conditional",
            "U": "Unsatisfactory",
            "UNSATISFACTORY": "Unsatisfactory",
        }
        safety_rating = safety_map.get(safety_raw, "Unrated")

        ins_raw = raw.get("bipd_insurance_on_file") or raw.get("insurance_amount")
        ins_amount = parse_safe_int(ins_raw, default=0)
        ins_on_file = bool(
            raw.get("insurance_on_file")
            or ins_amount > 0
            or str(ins_raw).strip().upper() in {"Y", "YES", "TRUE", "1"}
        )
        if ins_on_file and ins_amount == 0:
            ins_amount = 1000000

        cargo_types = raw.get("cargo_types")
        if not isinstance(cargo_types, list):
            cargo_types = []
            if str(raw.get("crgo_genfreight", "")).upper() == "X":
                cargo_types.append("Dry Van")
            if str(raw.get("crgo_reffood", "")).upper() == "X":
                cargo_types.append("Reefer")
            if str(raw.get("crgo_machlarge", "")).upper() == "X":
                cargo_types.append("Flatbed")
            if str(raw.get("hazmat_ind", "")).upper() in {"Y", "X"}:
                cargo_types.append("Hazmat")
            if not cargo_types:
                cargo_types = ["Dry Van"]

        equipment_tags = raw.get("equipment_tags")
        if not isinstance(equipment_tags, list):
            equipment_tags = list(cargo_types)

        normalized = {
            "dot_number": dot_number,
            "mc_number": clean_mc_number(mc_raw),
            "legal_name": str(raw.get("legal_name") or f"CARRIER {dot_number}").strip(),
            "dba_name": str(raw.get("dba_name") or "").strip(),
            "status": status,
            "authority_grant_date": grant_date,
            "authority_status": authority_status,
            "authority_type": authority_type,
            "authority_revoked_at": parse_safe_date(raw.get("authority_revoked_at")),
            "mcs150_date": mcs150_date,
            "operation_type": operation_type,
            "cargo_types": cargo_types,
            "equipment_tags": equipment_tags,
            "power_units": parse_safe_int(
                raw.get("nbr_power_unit") if "nbr_power_unit" in raw else raw.get("power_units"),
                default=1,
            ),
            "drivers": parse_safe_int(
                raw.get("driver_total") if "driver_total" in raw else raw.get("drivers"),
                default=1,
            ),
            "trailers": parse_safe_int(raw.get("trailers"), default=1),
            "state": str(raw.get("phy_state") or raw.get("state") or "").strip().upper(),
            "city": str(raw.get("phy_city") or raw.get("city") or "").strip().title(),
            "zip_code": str(raw.get("phy_zip") or raw.get("zip_code") or "").strip(),
            "address": str(raw.get("phy_street") or raw.get("address") or "").strip(),
            "country": str(raw.get("phy_country") or raw.get("country") or "US").strip().upper(),
            "phone": str(raw.get("telephone") or raw.get("phone") or "").strip(),
            "email": str(raw.get("email_address") or raw.get("email") or "").strip().lower(),
            "website": str(raw.get("website") or "").strip(),
            "owner_name": str(raw.get("owner_name") or raw.get("company_officer_1") or "").strip(),
            "safety_rating": safety_rating,
            "oos_percent": parse_safe_float(raw.get("oos_percent"), default=0.0),
            "crash_count_24m": parse_safe_int(raw.get("crash_count_24m"), default=0),
            "inspection_count_24m": parse_safe_int(raw.get("inspection_count_24m"), default=0),
            "basic_alerts": bool(raw.get("basic_alerts", False)),
            "insurance_on_file": ins_on_file,
            "insurance_amount": ins_amount,
            "insurance_expiry": parse_safe_date(raw.get("insurance_expiry")),
            "raw_json": raw,
        }
        return self.finalize_carrier_dict(normalized)


def generate_realistic_socrata_rows(count: int = 10000) -> list[dict]:
    """
    Generate realistic US trucking carrier census records matching Socrata schema
    so the user can immediately import 10,000+ carriers offline or behind a firewall
    and verify sub-second filtering on TX, new MCs (<90 days), fleet size, etc.
    """
    rng = random.Random(42)
    today = date.today()

    states_cities = [
        ("TX", "DALLAS", "75201", "214"),
        ("TX", "HOUSTON", "77002", "713"),
        ("TX", "FORT WORTH", "76102", "817"),
        ("TX", "SAN ANTONIO", "78205", "210"),
        ("TX", "EL PASO", "79901", "915"),
        ("CA", "FRESNO", "93721", "559"),
        ("CA", "ONTARIO", "91761", "909"),
        ("FL", "MIAMI", "33126", "305"),
        ("FL", "JACKSONVILLE", "32202", "904"),
        ("GA", "ATLANTA", "30303", "404"),
        ("IL", "CHICAGO", "60608", "312"),
        ("OH", "COLUMBUS", "43215", "614"),
        ("PA", "HARRISBURG", "17101", "717"),
        ("TN", "MEMPHIS", "38103", "901"),
        ("NC", "CHARLOTTE", "28202", "704"),
        ("IN", "INDIANAPOLIS", "46204", "317"),
        ("MO", "KANSAS CITY", "64106", "816"),
        ("AZ", "PHOENIX", "85004", "602"),
        ("WA", "SEATTLE", "98104", "206"),
        ("NJ", "NEWARK", "07102", "973"),
    ]
    prefixes = [
        "LONE STAR", "EAGLE", "HORIZON", "APEX", "PRIME", "LIBERTY", "SUMMIT",
        "FALCON", "TITAN", "PIONEER", "BLUE RIDGE", "IRONHORSE", "SILVERLINE",
        "INTERSTATE", "PATRIOT", "HEARTLAND", "ATLAS", "RED RIVER", "CANYON",
        "VELOCITY", "FRONTIER", "DIAMOND", "HIGHWAY", "CROSSROAD", "RELIABLE",
    ]
    suffixes = [
        "TRANSPORT LLC", "LOGISTICS INC", "TRUCKING LLC", "FREIGHT SYSTEMS",
        "CARRIERS LLC", "EXPRESS INC", "HAULING LLC", "DISPATCH & FREIGHT",
        "MOTOR LINES", "TRANSIT GROUP",
    ]
    cargo_Work = [
        ["Dry Van"],
        ["Reefer"],
        ["Flatbed"],
        ["Dry Van", "Reefer"],
        ["Dry Van", "Flatbed"],
        ["Flatbed", "Power Only"],
        ["Box Truck"],
        ["Dry Van", "Hazmat"],
    ]
    first_names = ["MICHAEL", "DAVID", "CARLOS", "JAMES", "ROBERT", "MARCUS", "KEVIN", "DANIEL", "JOSE", "BRANDON"]
    last_names = ["MILLER", "RODRIGUEZ", "JOHNSON", "WILLIAMS", "GARCIA", "SMITH", "DAVIS", "MARTINEZ", "CLARK", "LEWIS"]

    rows = []
    base_dot = 3800000
    base_mc = 1500000

    for i in range(count):
        dot_num = str(base_dot + i)
        mc_num = f"MC-{base_mc + i}"
        state, city, zip_c, area = states_cities[i % len(states_cities)]
        p_name = prefixes[i % len(prefixes)]
        s_name = suffixes[(i // len(prefixes)) % len(suffixes)]
        legal_name = f"{p_name} {s_name} {i + 1}"
        dba_name = f"{p_name} EXPRESS" if i % 4 == 0 else ""

        # Make ~35% of carriers under 90 days old (hot dispatch leads)
        if i % 3 == 0:
            age_days = rng.randint(2, 88)
        elif i % 3 == 1:
            age_days = rng.randint(90, 360)
        else:
            age_days = rng.randint(365, 1800)

        grant_date = (today - timedelta(days=age_days)).isoformat()
        mcs150_date = (today - timedelta(days=max(1, age_days - 5))).isoformat()

        # Fleet size: mostly 1-10 trucks (owner-operators & small fleets)
        if i % 5 != 0:
            power_units = rng.randint(1, 6)
        else:
            power_units = rng.randint(7, 35)
        drivers = max(1, power_units + rng.randint(0, 2))

        phone = f"({area}) {rng.randint(200, 989)}-{rng.randint(1000, 9999)}" if i % 15 != 0 else ""
        has_email = i % 3 != 0
        email = f"dispatch{i + 1}@carrier{dot_num}.com" if has_email else ""
        website = f"https://www.carrier{dot_num}.com" if i % 5 == 0 else ""
        owner = f"{first_names[i % len(first_names)]} {last_names[(i * 3) % len(last_names)]}" if i % 2 == 0 else ""

        auth_status = "A" if i % 12 != 0 else ("P" if i % 24 == 0 else "I")
        ins_on_file = i % 10 != 0
        ins_amount = 1000000 if ins_on_file else 0
        # Some expiring within 30 days for alert testing
        if ins_on_file:
            if i % 9 == 0:
                ins_expiry = (today + timedelta(days=rng.randint(3, 25))).isoformat()
            else:
                ins_expiry = (today + timedelta(days=rng.randint(45, 320))).isoformat()
        else:
            ins_expiry = None

        safety = "S" if i % 4 == 0 else ("C" if i % 17 == 0 else "")
        crashes = 1 if i % 20 == 0 else 0
        inspections = rng.randint(0, 14)
        oos_pct = round(rng.uniform(0.0, 28.5), 1) if inspections > 0 else 0.0
        cargo = cargo_Work[i % len(cargo_Work)]

        rows.append(
            {
                "dot_number": dot_num,
                "mc_mx_ff_number": mc_num,
                "legal_name": legal_name,
                "dba_name": dba_name,
                "status_code": "A" if auth_status != "I" else "I",
                "common_stat": auth_status,
                "contract_stat": "A" if i % 6 == 0 else "N",
                "authority_grant_date": grant_date,
                "mcs150_date": mcs150_date,
                "carrier_operation": "A" if i % 8 != 0 else "C",
                "cargo_types": cargo,
                "equipment_tags": cargo,
                "nbr_power_unit": str(power_units),
                "driver_total": str(drivers),
                "trailers": str(power_units),
                "phy_state": state,
                "phy_city": city,
                "phy_zip": zip_c,
                "phy_street": f"{100 + (i % 8900)} INDUSTRIAL BLVD",
                "phy_country": "US",
                "telephone": phone,
                "email_address": email,
                "website": website,
                "company_officer_1": owner,
                "safety_rating": safety,
                "oos_percent": oos_pct,
                "crash_count_24m": crashes,
                "inspection_count_24m": inspections,
                "basic_alerts": oos_pct > 22.0,
                "bipd_insurance_on_file": str(ins_amount),
                "insurance_on_file": ins_on_file,
                "insurance_expiry": ins_expiry,
            }
        )
    return rows

