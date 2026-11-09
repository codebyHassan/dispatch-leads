from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from carriers.models import Carrier
from crm.models import Activity, AuditLog, Contact, Lead, Note, Task, Template
from sync.models import Settings

User = get_user_model()


class Sprint3CRMPipelineAndEnrichmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="leadagent", password="password123")
        self.client.login(username="leadagent", password="password123")
        today = date.today()

        self.carrier = Carrier.objects.create(
            dot_number="880011",
            mc_number="128800",
            legal_name="PINNACLE FREIGHT GROUP LLC",
            state="TX",
            city="Fort Worth",
            zip_code="76102",
            authority_status="Active",
            authority_grant_date=today - timedelta(days=20),
            power_units=4,
            drivers=4,
            phone="(817) 555-4433",
            phone_e164="+18175554433",
            email="dispatch@pinnacle.com",
            email_valid=True,
            insurance_on_file=True,
            insurance_amount=1000000,
        )

        Template.objects.create(
            name="Pitch Script",
            type="script",
            body="Hello {carrier_name}, calling about MC-{mc_number} in {state} with {power_units} trucks."
        )

    def test_duplicate_lead_protection(self):
        # Adding same carrier twice creates exactly 1 lead
        r1 = self.client.get(reverse("add_carrier_to_leads", args=[self.carrier.dot_number]))
        self.assertEqual(r1.status_code, 302)
        lead_id = Lead.objects.filter(carrier=self.carrier, owner=self.user).first().pk

        r2 = self.client.get(reverse("add_carrier_to_leads", args=[self.carrier.dot_number]))
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(Lead.objects.filter(carrier=self.carrier, owner=self.user).count(), 1)
        self.assertIn(f"/leads/{lead_id}/", r2.url)

    def test_manual_contact_enrichment_and_protection(self):
        lead = Lead.objects.create(carrier=self.carrier, owner=self.user, status="New")
        enrich_data = {
            "phone": "(214) 555-9988",
            "email": "owner@pinnacle.com",
            "website": "https://www.pinnaclefreight.com",
            "owner_name": "Marcus Vance",
            "source": "Call",
        }
        resp = self.client.post(reverse("lead_manual_enrich", args=[lead.pk]), enrich_data)
        self.assertEqual(resp.status_code, 302)

        self.carrier.refresh_from_db()
        self.assertEqual(self.carrier.phone_e164, "+12145559988")
        self.assertEqual(self.carrier.email, "owner@pinnacle.com")
        self.assertEqual(self.carrier.owner_name, "Marcus Vance")
        self.assertTrue(self.carrier.phone_added_by_user)
        self.assertEqual(self.carrier.phone_source, "Call")
        self.assertTrue(AuditLog.objects.filter(object_type="CarrierEnrichment", object_id="880011").exists())

    def test_lead_status_change_cadence_and_audit(self):
        lead = Lead.objects.create(carrier=self.carrier, owner=self.user, status="New")
        resp = self.client.post(
            reverse("lead_update_status", args=[lead.pk]),
            {"status": "Contacted"}
        )
        self.assertEqual(resp.status_code, 302)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "Contacted")
        self.assertIsNotNone(lead.last_contact_at)
        # Automatic 2-day follow-up cadence task created
        self.assertTrue(lead.tasks.filter(is_done=False).exists())
        self.assertTrue(Activity.objects.filter(lead=lead, type="system").exists())

    def test_csv_lead_export_and_import(self):
        lead = Lead.objects.create(carrier=self.carrier, owner=self.user, status="Interested")
        exp_resp = self.client.get(reverse("export_leads_csv"))
        self.assertEqual(exp_resp.status_code, 200)
        self.assertIn("PINNACLE FREIGHT GROUP LLC", exp_resp.content.decode("utf-8"))

        # Test import
        c2 = Carrier.objects.create(dot_number="990022", legal_name="IMPORTED LOGISTICS LLC")
        csv_content = f"DOT Number,Status\n{c2.dot_number},Negotiation\n"
        csv_file = SimpleUploadedFile("leads.csv", csv_content.encode("utf-8"), content_type="text/csv")
        imp_resp = self.client.post(reverse("import_leads_csv"), {"csv_file": csv_file})
        self.assertEqual(imp_resp.status_code, 302)
        self.assertTrue(Lead.objects.filter(carrier=c2, owner=self.user, status="Negotiation").exists())

    def test_sqlite_backup_download(self):
        resp = self.client.get(reverse("download_backup_db"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="dispatch_leads_backup.sqlite3"')
