# Official Data Sources & Field Mapping Specification

Per PRD Section 4, this document records the exact upstream field names from public US transport datasets and how they normalize into the internal `CarrierDict` / `Carrier` model.

---

## 1. FMCSA Open Data — Socrata API (`data.transportation.gov`)
- **Dataset:** Motor Carrier Census Information (`az4n-8mr2` / `kjg3-diqy`) & Licensing/Insurance (`6eyk-hxee`)
- **Endpoint Format:** `https://data.transportation.gov/resource/az4n-8mr2.json?$limit=1000&$offset=0`
- **Authentication:** Optional `X-App-Token` header; public unauthenticated requests supported with polite rate limiting.

### Exact Socrata Field Names -> Internal `Carrier` Model Fields
| Socrata Field Name | Example Value | Internal Field | Notes |
|---|---|---|---|
| `dot_number` | `"3984120"` | `dot_number` | Primary unique identifier (string/digits) |
| `mc_mx_ff_number` or `docket_number` | `"MC-1492011"` / `"1492011"` | `mc_number` | Normalized to numeric digits (`1492011`) |
| `legal_name` | `"LONE STAR FREIGHT LLC"` | `legal_name` | Primary company name |
| `dba_name` | `"LONE STAR LOGISTICS"` | `dba_name` | Doing-business-as name |
| `status_code` | `"A"` | `status` | `"A"` -> `"Active"`, `"I"` -> `"Inactive"` |
| `add_date` / `authority_grant_date` | `"2026-09-15"` | `authority_grant_date` | Parsed `YYYY-MM-DD` or `YYYYMMDD` |
| `common_stat` / `contract_stat` | `"A"` / `"N"` | `authority_status`, `authority_type` | Determines `Active`/`Pending`/`Inactive` & `Common`/`Contract` |
| `carrier_operation` | `"A"` | `operation_type` | `"A"` -> `"Interstate"`, `"B"` -> `"Intrastate Hazmat"`, `"C"` -> `"Intrastate Non-Hazmat"` |
| `nbr_power_unit` or `power_units` | `"4"` | `power_units` | Integer count of trucks/power units |
| `driver_total` or `total_drivers` | `"5"` | `drivers` | Integer count of drivers |
| `phy_state` | `"TX"` | `state` | 2-letter US state code (indexed) |
| `phy_city` | `"DALLAS"` | `city` | Physical city |
| `phy_zip` | `"75201"` | `zip_code` | Physical ZIP code |
| `phy_street` | `"1200 COMMERCE ST"` | `address` | Physical street address |
| `telephone` or `phone` | `"(214) 555-0192"` | `phone`, `phone_e164` | Cleaned to E.164 (`+12145550192`) |
| `email_address` | `"dispatch@lonestar.com"` | `email`, `email_valid` | Validated format |
| `mcs150_date` | `"2026-08-01"` | `mcs150_date` | Last MCS-150 filing date |
| `safety_rating` | `"S"` / `"C"` / `"U"` / `""` | `safety_rating` | `"Satisfactory"`, `"Conditional"`, `"Unsatisfactory"`, `"Unrated"` |
| `bipd_insurance_on_file` | `"1000000"` / `"Y"` | `insurance_on_file`, `insurance_amount` | Liability coverage on file |

---

## 2. FMCSA QCMobile API (`mobile.fmcsa.dot.gov`)
- **Base URL:** `https://mobile.fmcsa.dot.gov/qc/services/carriers/{dot_number}?webKey={WEBKEY}`
- **Docket Lookup:** `https://mobile.fmcsa.dot.gov/qc/services/carriers/docket-number/{mc_number}?webKey={WEBKEY}`

### Exact QCMobile JSON Keys (`content.carrier`) -> Internal `Carrier` Model Fields
| QCMobile Key | Internal Field | Notes |
|---|---|---|
| `dotNumber` | `dot_number` | Integer/string DOT number |
| `mcNumber` | `mc_number` | Optional docket number |
| `legalName` | `legal_name` | Legal company name |
| `dbaName` | `dba_name` | DBA name |
| `allowedToOperate` | `status` | `"Y"` -> `"Active"`, `"N"` -> `"Inactive"` |
| `commonAuthorityStatus` | `authority_status` | `"A"` -> `"Active"`, `"I"` -> `"Inactive"`, `"P"` -> `"Pending"` |
| `contractAuthorityStatus` | `authority_type` | Used with commonAuthorityStatus |
| `totalPowerUnits` | `power_units` | Fleet power unit count |
| `totalDrivers` | `drivers` | Fleet driver count |
| `phyStreet`, `phyCity`, `phyState`, `phyZipcode` | `address`, `city`, `state`, `zip_code` | Physical location |
| `telephone` | `phone`, `phone_e164` | Cleaned to E.164 |
| `safetyRating` | `safety_rating` | `"S"`, `"C"`, `"U"`, or `None` -> `"Unrated"` |
| `oosRateNationalAverage` / `vehicleOosRate` | `oos_percent` | Float OOS percentage |
| `crashTotal` | `crash_count_24m` | 24-month total crashes |
| `driverInsp` + `vehicleInsp` | `inspection_count_24m` | 24-month total inspections |
| `bipdInsuranceOnFile` | `insurance_on_file`, `insurance_amount` | `"1"` / dollar string |
| `mcs150Outdated` | — | Used in raw JSON inspection |

---

## 3. FMCSA SAFER Company Snapshot HTML Fallback (`safer.fmcsa.dot.gov`)
- **Query URL:** `https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string={dot_number}`
- **Parsed HTML Table Labels (`<th>` / `<A class="querylabelbkg">`):**
  - `USDOT Number:` -> `dot_number`
  - `MC/MX/FF Number(s):` -> `mc_number`
  - `Legal Name:` -> `legal_name`
  - `DBA Name:` -> `dba_name`
  - `Physical Address:` -> `address`, `city`, `state`, `zip_code`
  - `Phone:` -> `phone`, `phone_e164`
  - `Power Units:` -> `power_units`
  - `Drivers:` -> `drivers`
  - `MCS-150 Form Date:` -> `mcs150_date`
  - `Operating Authority Status:` -> `authority_status`
  - `Safety Rating:` -> `safety_rating`
  - `Cargo Carried:` -> `cargo_types` (checked `X` rows: `General Freight`, `Refrigerated Food`, `Machinery, Large Objects`, `Fresh Produce`, `Building Materials`, `Intermodal Containers`, `Motor Vehicles`, etc.)

---

## 4. Compliance & Caching Rules
1. Every outbound request uses the configured `Settings.proxy_url` (HTTP or SOCKS5) if present.
2. Polite `User-Agent: DispatchLeadFinder/1.0 (B2B Carrier Compliance Tool)` header on all requests.
3. Configurable `request_delay_ms` between requests and retry with exponential backoff on `429` / `503`.
4. Responses are cached on the `Carrier` record (`last_synced_at`, `raw_json`) and skipped during routine refresh if fresher than `Settings.freshness_hours` (unless `force=True` is requested).

