from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from carriers.models import Carrier, SavedFilter
from crm.models import Lead
from sync.services import upsert_carrier_dict

User = get_user_model()


class Sprint2SearchRefreshAndExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sales", password="password123")
        self.client.login(username="sales", password="password123")
        today = date.today()

        self.c1 = Carrier.objects.create(
            dot_number="700101",
            mc_number="900101",
            legal_name="TEXAS HOT REEFERS LLC",
            state="TX",
            city="Dallas",
            zip_code="75201",
            authority_status="Active",
            authority_grant_date=today - timedelta(days=25),
            power_units=3,
            drivers=3,
            cargo_types=["Reefer"],
            phone="(214) 555-1001",
            email="dispatch@txhot.com",
            insurance_on_file=True,
            insurance_amount=1000000,
            insurance_expiry=today + timedelta(days=15),
        )
        self.c2 = Carrier.objects.create(
            dot_number="700102",
            mc_number="900102",
            legal_name="DNC BLOCKED CARRIER INC",
            state="TX",
            city="Houston",
            zip_code="77002",
            authority_status="Active",
            authority_grant_date=today - timedelta(days=10),
            power_units=2,
            drivers=2,
            phone="(713) 555-2002",
        )
        # Mark c2 as Do Not Contact
        Lead.objects.create(
            carrier=self.c2,
            owner=self.user,
            status="Do Not Contact",
            dnc_reason="Requested removal",
        )

    def test_dnc_carrier_hidden_from_default_search_and_csv_export(self):
        resp = self.client.get(reverse("carrier_list") + "?state=TX&mc_age_max=90")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("TEXAS HOT REEFERS LLC", content)
        self.assertNotIn("DNC BLOCKED CARRIER INC", content)

        csv_resp = self.client.get(reverse("export_carriers_csv") + "?state=TX&mc_age_max=90")
        self.assertEqual(csv_resp.status_code, 200)
        csv_text = csv_resp.content.decode("utf-8")
        self.assertIn("700101", csv_text)
        self.assertNotIn("700102", csv_text)

    def test_save_and_reload_filter_preset(self):
        qstr = "mc_age_max=90&state=TX&power_min=2&power_max=5&cargo_type=Reefer"
        resp = self.client.post(
            reverse("save_filter"),
            {"name": "TX Reefer 2-5 Trucks", "query_string": qstr},
        )
        self.assertEqual(resp.status_code, 302)
        sf = SavedFilter.objects.get(user=self.user, name="TX Reefer 2-5 Trucks")
        self.assertEqual(sf.query_string, qstr)

        reload_resp = self.client.get(f"/carriers/?{sf.query_string}&saved_filter_id={sf.pk}")
        self.assertEqual(reload_resp.status_code, 200)
        self.assertEqual(reload_resp.context["params"].get("cargo_type"), "Reefer")
        self.assertEqual(reload_resp.context["params"].get("power_min"), "2")

    def test_bulk_actions_add_leads_and_skip_dnc(self):
        resp = self.client.post(
            reverse("bulk_carrier_action"),
            {
                "bulk_action": "add_to_leads",
                "selected_dots": ["700101", "700102"],
                "return_query": "state=TX",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Lead.objects.filter(carrier=self.c1, owner=self.user, status="New").exists()
        )
        self.assertEqual(Lead.objects.filter(carrier=self.c1, owner=self.user).count(), 1)

    def test_carrier_refresh_and_change_tracking(self):
        # Update power_units via upsert_carrier_dict to verify CarrierChange record
        upsert_carrier_dict(
            {
                "dot_number": "700101",
                "legal_name": "TEXAS HOT REEFERS LLC",
                "power_units": 6,
                "authority_status": "Inactive",
            }
        )
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.power_units, 6)
        self.assertTrue(self.c1.has_authority_alert)
        self.assertTrue(self.c1.changes.filter(field="power_units", old_value="3", new_value="6").exists())

        # Also test POST /carriers/<dot>/refresh/ endpoint
        r = self.client.post(reverse("carrier_refresh", args=["700101"]))
        self.assertEqual(r.status_code, 302)
