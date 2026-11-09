from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from carriers.filters import apply_carrier_filters
from carriers.models import Carrier
from carriers.utils import is_valid_email, normalize_phone_e164, resolve_timezone
from sync.connectors.socrata import SocrataConnector
from sync.models import Settings, SyncJob
from sync.services import upsert_carrier_dict

User = get_user_model()


class Sprint1FoundationAndSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="agent", password="password123")
        self.cfg = Settings.get_solo()

    def test_phone_e164_and_email_cleanup(self):
        self.assertEqual(normalize_phone_e164("(214) 555-0199"), "+12145550199")
        self.assertEqual(normalize_phone_e164("1-800-555-1234"), "+18005551234")
        self.assertTrue(is_valid_email("dispatch@lonestar.com"))
        self.assertFalse(is_valid_email("N/A"))
        self.assertEqual(resolve_timezone("TX", "75201"), "America/Chicago")
        self.assertEqual(resolve_timezone("TX", "79901"), "America/Denver")

    def test_socrata_connector_normalization_and_mc_age(self):
        connector = SocrataConnector(cfg=self.cfg)
        grant_dt = (date.today() - timedelta(days=45)).isoformat()
        raw_sample = {
            "dot_number": "4100200",
            "mc_mx_ff_number": "MC-1620300",
            "legal_name": "APEX TEXAS LOGISTICS LLC",
            "status_code": "A",
            "common_stat": "A",
            "authority_grant_date": grant_dt,
            "nbr_power_unit": "4",
            "driver_total": "4",
            "phy_state": "TX",
            "phy_city": "DALLAS",
            "phy_zip": "75201",
            "telephone": "(214) 555-0144",
            "email_address": "ops@apextx.com",
            "bipd_insurance_on_file": "1000000",
        }
        norm = connector.normalize(raw_sample)
        self.assertEqual(norm["dot_number"], "4100200")
        self.assertEqual(norm["mc_number"], "1620300")
        self.assertEqual(norm["phone_e164"], "+12145550144")
        self.assertTrue(norm["email_valid"])

        carrier, created, _ = upsert_carrier_dict(norm)
        self.assertTrue(created)
        self.assertEqual(carrier.mc_age_days, 45)
        self.assertTrue(carrier.is_new_authority)
        self.assertEqual(carrier.mc_age_display, "45 days")

    def test_user_edited_contact_not_overwritten_by_sync(self):
        carrier = Carrier.objects.create(
            dot_number="4999111",
            legal_name="PROTECTED PHONE CARRIER",
            phone="(214) 555-9999",
            phone_e164="+12145559999",
            phone_added_by_user=True,
            phone_source="Call",
        )
        upsert_carrier_dict(
            {
                "dot_number": "4999111",
                "legal_name": "PROTECTED PHONE CARRIER",
                "phone": "(800) 000-0000",
                "phone_e164": "+18000000000",
                "power_units": 5,
            }
        )
        carrier.refresh_from_db()
        self.assertEqual(carrier.phone_e164, "+12145559999")
        self.assertEqual(carrier.power_units, 5)

    def test_filter_new_mc_under_90_days_in_tx(self):
        today = date.today()
        Carrier.objects.create(
            dot_number="5001",
            legal_name="HOT TX CARRIER",
            state="TX",
            authority_grant_date=today - timedelta(days=30),
        )
        Carrier.objects.create(
            dot_number="5002",
            legal_name="OLD TX CARRIER",
            state="TX",
            authority_grant_date=today - timedelta(days=200),
        )
        qd = QueryDict("mc_age_max=90&state=TX")
        qs = apply_carrier_filters(Carrier.objects.all(), qd, user=self.user)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().dot_number, "5001")

    def test_views_require_login_and_render(self):
        resp = self.client.get(reverse("sync_dashboard"))
        self.assertEqual(resp.status_code, 302)

        self.client.login(username="agent", password="password123")
        for url_name in ["dashboard", "carrier_list", "sync_dashboard", "settings"]:
            r = self.client.get(reverse(url_name))
            self.assertEqual(r.status_code, 200)

        job = SyncJob.objects.create(type="seed_realistic", status="done", total=100, processed=100)
        status_resp = self.client.get(reverse("sync_job_status", args=[job.pk]))
        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(status_resp.json()["progress_percent"], 100)
