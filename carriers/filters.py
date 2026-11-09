from datetime import date, timedelta
from django.db.models import Q
from dateutil import parser as date_parser
from carriers.models import Carrier
from crm.models import Lead


def apply_carrier_filters(queryset, params, user=None):
    """
    Apply all server-side carrier search filters from URL query parameters.
    By default, hides carriers marked 'Do Not Contact' unless lead_state='Do Not Contact' is explicitly selected.
    """
    qs = queryset

    # Top search bar / general query
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(legal_name__icontains=q)
            | Q(dba_name__icontains=q)
            | Q(dot_number__icontains=q)
            | Q(mc_number__icontains=q)
            | Q(phone__icontains=q)
            | Q(phone_e164__icontains=q)
            | Q(email__icontains=q)
        )

    # Identity
    mc_number = (params.get("mc_number") or "").strip()
    if mc_number:
        clean_mc = "".join(ch for ch in mc_number if ch.isdigit())
        qs = qs.filter(mc_number__icontains=clean_mc or mc_number)

    dot_number = (params.get("dot_number") or "").strip()
    if dot_number:
        qs = qs.filter(dot_number__icontains=dot_number)

    legal_name = (params.get("legal_name") or "").strip()
    if legal_name:
        qs = qs.filter(legal_name__icontains=legal_name)

    dba_name = (params.get("dba_name") or "").strip()
    if dba_name:
        qs = qs.filter(dba_name__icontains=dba_name)

    # Authority & MC Age (mc_age_days = today - authority_grant_date)
    today = date.today()
    mc_age_unit = (params.get("mc_age_unit") or "days").strip().lower()
    multiplier = 365 if mc_age_unit == "years" else (30 if mc_age_unit == "months" else 1)

    mc_age_min = (params.get("mc_age_min") or "").strip()
    if mc_age_min.isdigit():
        min_days = int(mc_age_min) * multiplier
        max_grant_date = today - timedelta(days=min_days)
        qs = qs.filter(authority_grant_date__lte=max_grant_date)

    mc_age_max = (params.get("mc_age_max") or "").strip()
    if mc_age_max.isdigit():
        max_days = int(mc_age_max) * multiplier
        min_grant_date = today - timedelta(days=max_days)
        qs = qs.filter(
            authority_grant_date__gte=min_grant_date,
            authority_grant_date__lte=today,
        )

    grant_from = (params.get("grant_from") or "").strip()
    if grant_from:
        try:
            qs = qs.filter(authority_grant_date__gte=date_parser.parse(grant_from).date())
        except Exception:
            pass

    grant_to = (params.get("grant_to") or "").strip()
    if grant_to:
        try:
            qs = qs.filter(authority_grant_date__lte=date_parser.parse(grant_to).date())
        except Exception:
            pass

    authority_status = (params.get("authority_status") or "").strip()
    if authority_status:
        qs = qs.filter(authority_status__iexact=authority_status)

    authority_type = (params.get("authority_type") or "").strip()
    if authority_type:
        qs = qs.filter(authority_type__iexact=authority_type)

    # Location
    state = (params.get("state") or "").strip().upper()
    if state:
        qs = qs.filter(state=state)

    city = (params.get("city") or "").strip()
    if city:
        qs = qs.filter(city__icontains=city)

    zip_code = (params.get("zip_code") or "").strip()
    radius_miles = (params.get("radius_miles") or "").strip()
    if zip_code:
        if radius_miles.isdigit() and int(radius_miles) > 0 and len(zip_code) >= 3:
            # Approximate regional radius using 3-digit SCF ZIP prefix
            qs = qs.filter(zip_code__startswith=zip_code[:3])
        else:
            qs = qs.filter(zip_code__startswith=zip_code)

    country = (params.get("country") or "").strip().upper()
    if country:
        qs = qs.filter(country=country)

    # Fleet
    power_min = (params.get("power_min") or "").strip()
    if power_min.isdigit():
        qs = qs.filter(power_units__gte=int(power_min))

    power_max = (params.get("power_max") or "").strip()
    if power_max.isdigit():
        qs = qs.filter(power_units__lte=int(power_max))

    drivers_min = (params.get("drivers_min") or "").strip()
    if drivers_min.isdigit():
        qs = qs.filter(drivers__gte=int(drivers_min))

    drivers_max = (params.get("drivers_max") or "").strip()
    if drivers_max.isdigit():
        qs = qs.filter(drivers__lte=int(drivers_max))

    trailers_min = (params.get("trailers_min") or "").strip()
    if trailers_min.isdigit():
        qs = qs.filter(trailers__gte=int(trailers_min))

    trailers_max = (params.get("trailers_max") or "").strip()
    if trailers_max.isdigit():
        qs = qs.filter(trailers__lte=int(trailers_max))

    # Operation & Cargo
    operation_type = (params.get("operation_type") or "").strip()
    if operation_type:
        qs = qs.filter(operation_type__iexact=operation_type)

    cargo_type = (params.get("cargo_type") or "").strip()
    if cargo_type:
        qs = qs.filter(cargo_types__icontains=cargo_type)

    equipment = (params.get("equipment") or "").strip()
    if equipment:
        qs = qs.filter(equipment_tags__icontains=equipment)

    # Safety
    safety_rating = (params.get("safety_rating") or "").strip()
    if safety_rating:
        qs = qs.filter(safety_rating__iexact=safety_rating)

    oos_max = (params.get("oos_max") or "").strip()
    if oos_max:
        try:
            qs = qs.filter(oos_percent__lte=float(oos_max))
        except ValueError:
            pass

    crashes_max = (params.get("crashes_max") or "").strip()
    if crashes_max.isdigit():
        qs = qs.filter(crash_count_24m__lte=int(crashes_max))

    inspections_min = (params.get("inspections_min") or "").strip()
    if inspections_min.isdigit():
        qs = qs.filter(inspection_count_24m__gte=int(inspections_min))

    inspections_max = (params.get("inspections_max") or "").strip()
    if inspections_max.isdigit():
        qs = qs.filter(inspection_count_24m__lte=int(inspections_max))

    basic_alerts = (params.get("basic_alerts") or "").strip().lower()
    if basic_alerts == "yes":
        qs = qs.filter(basic_alerts=True)
    elif basic_alerts == "no":
        qs = qs.filter(basic_alerts=False)

    # Insurance
    insurance_on_file = (params.get("insurance_on_file") or "").strip().lower()
    if insurance_on_file == "yes":
        qs = qs.filter(insurance_on_file=True)
    elif insurance_on_file == "no":
        qs = qs.filter(insurance_on_file=False)

    liability_min = (params.get("liability_min") or "").strip()
    if liability_min.isdigit():
        qs = qs.filter(insurance_amount__gte=int(liability_min))

    insurance_expiring = (params.get("insurance_expiring") or "").strip().lower()
    if insurance_expiring.isdigit():
        days_win = int(insurance_expiring)
        qs = qs.filter(
            insurance_expiry__gte=today,
            insurance_expiry__lte=today + timedelta(days=days_win),
        )
    elif insurance_expiring == "expired":
        qs = qs.filter(insurance_expiry__lt=today)

    # Contact completeness
    has_phone = (params.get("has_phone") or "").strip().lower()
    if has_phone == "yes":
        qs = qs.exclude(phone="").exclude(phone_e164="")
    elif has_phone == "no":
        qs = qs.filter(phone="")

    has_email = (params.get("has_email") or "").strip().lower()
    if has_email == "yes":
        qs = qs.filter(email_valid=True).exclude(email="")
    elif has_email == "no":
        qs = qs.filter(Q(email="") | Q(email_valid=False))

    has_website = (params.get("has_website") or "").strip().lower()
    if has_website == "yes":
        qs = qs.exclude(website="")
    elif has_website == "no":
        qs = qs.filter(website="")

    has_verified_contact = (params.get("has_verified_contact") or "").strip().lower()
    if has_verified_contact == "yes":
        qs = qs.filter(
            Q(phone_added_by_user=True)
            | Q(email_added_by_user=True)
            | Q(owner_added_by_user=True)
            | Q(leads__contacts__added_by_user=True)
        ).distinct()
    elif has_verified_contact == "no":
        qs = qs.filter(
            phone_added_by_user=False,
            email_added_by_user=False,
            owner_added_by_user=False,
        )

    # Data freshness
    updated_after = (params.get("updated_after") or "").strip()
    if updated_after:
        try:
            qs = qs.filter(last_synced_at__date__gte=date_parser.parse(updated_after).date())
        except Exception:
            pass

    updated_before = (params.get("updated_before") or "").strip()
    if updated_before:
        try:
            qs = qs.filter(last_synced_at__date__lte=date_parser.parse(updated_before).date())
        except Exception:
            pass

    # Lead state & Do Not Contact hiding
    lead_state = (params.get("lead_state") or "").strip()
    if lead_state == "Not a lead":
        if user and user.is_authenticated:
            qs = qs.exclude(leads__owner=user)
        else:
            qs = qs.filter(leads__isnull=True)
    elif lead_state:
        if user and user.is_authenticated:
            qs = qs.filter(leads__owner=user, leads__status=lead_state)
        else:
            qs = qs.filter(leads__status=lead_state)

    # Default view hides carriers marked Do Not Contact unless explicitly filtering for them
    if lead_state != "Do Not Contact":
        dnc_carrier_ids = Lead.objects.filter(status="Do Not Contact").values_list(
            "carrier_id", flat=True
        )
        qs = qs.exclude(id__in=dnc_carrier_ids)

    return qs

