from .base import (
    BaseConnector,
    clean_mc_number,
    parse_safe_date,
    parse_safe_float,
    parse_safe_int,
)


class QCMobileConnector(BaseConnector):
    """
    Connector for FMCSA QCMobile API (mobile.fmcsa.dot.gov).
    Requires a free FMCSA webKey configured in Settings.qcmobile_webkey.
    """

    source_name = "qcmobile"
    BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services/carriers"

    def fetch(self, identifier: str) -> dict:
        webkey = (self.cfg.qcmobile_webkey or "").strip()
        if not webkey:
            raise ValueError("FMCSA QCMobile webKey is not configured in Settings.")
        dot_num = str(identifier).strip()
        url = f"{self.BASE_URL}/{dot_num}"
        resp = self.request_with_backoff("GET", url, params={"webKey": webkey})
        payload = resp.json()
        if isinstance(payload, dict):
            content = payload.get("content") or payload
            if isinstance(content, dict) and "carrier" in content:
                return content["carrier"] or {}
            if isinstance(content, list) and content:
                first = content[0]
                return first.get("carrier", first) if isinstance(first, dict) else {}
        return {}

    def normalize(self, raw: dict) -> dict:
        dot_number = str(raw.get("dotNumber") or raw.get("dot_number") or "").strip()
        allowed = str(raw.get("allowedToOperate") or "Y").strip().upper()
        status = "Active" if allowed == "Y" else "Inactive"

        common_stat = str(raw.get("commonAuthorityStatus") or "A").strip().upper()
        contract_stat = str(raw.get("contractAuthorityStatus") or "N").strip().upper()

        if common_stat == "A" or contract_stat == "A":
            authority_status = "Active"
        elif common_stat == "P" or contract_stat == "P":
            authority_status = "Pending"
        else:
            authority_status = "Inactive"

        if common_stat == "A" and contract_stat == "A":
            authority_type = "Both"
        elif contract_stat == "A":
            authority_type = "Contract"
        else:
            authority_type = "Common"

        safety_code = str(raw.get("safetyRating") or "").strip().upper()
        safety_map = {
            "S": "Satisfactory",
            "C": "Conditional",
            "U": "Unsatisfactory",
        }
        safety_rating = safety_map.get(safety_code, "Unrated")

        ins_raw = raw.get("bipdInsuranceOnFile")
        ins_amount = parse_safe_int(ins_raw, default=0)
        ins_on_file = ins_amount > 0 or str(ins_raw).strip().upper() in {"Y", "1", "TRUE"}
        if ins_on_file and ins_amount <= 1:
            ins_amount = 1000000

        driver_insp = parse_safe_int(raw.get("driverInsp"), default=0)
        vehicle_insp = parse_safe_int(raw.get("vehicleInsp"), default=0)

        normalized = {
            "dot_number": dot_number,
            "mc_number": clean_mc_number(raw.get("mcNumber") or raw.get("docketNumber") or ""),
            "legal_name": str(raw.get("legalName") or f"CARRIER {dot_number}").strip(),
            "dba_name": str(raw.get("dbaName") or "").strip(),
            "status": status,
            "authority_grant_date": parse_safe_date(raw.get("addDate") or raw.get("authorityGrantDate")),
            "authority_status": authority_status,
            "authority_type": authority_type,
            "mcs150_date": parse_safe_date(raw.get("mcs150FormDate")),
            "operation_type": "Interstate" if str(raw.get("carrierOperation", "A")).upper() == "A" else "Intrastate",
            "power_units": parse_safe_int(raw.get("totalPowerUnits"), default=1),
            "drivers": parse_safe_int(raw.get("totalDrivers"), default=1),
            "state": str(raw.get("phyState") or "").strip().upper(),
            "city": str(raw.get("phyCity") or "").strip().title(),
            "zip_code": str(raw.get("phyZipcode") or "").strip(),
            "address": str(raw.get("phyStreet") or "").strip(),
            "country": str(raw.get("phyCountry") or "US").strip().upper(),
            "phone": str(raw.get("telephone") or "").strip(),
            "email": str(raw.get("emailAddress") or "").strip().lower(),
            "safety_rating": safety_rating,
            "oos_percent": parse_safe_float(raw.get("vehicleOosRate") or raw.get("driverOosRate"), default=0.0),
            "crash_count_24m": parse_safe_int(raw.get("crashTotal"), default=0),
            "inspection_count_24m": driver_insp + vehicle_insp,
            "insurance_on_file": ins_on_file,
            "insurance_amount": ins_amount,
            "raw_json": raw,
        }
        return self.finalize_carrier_dict(normalized)

