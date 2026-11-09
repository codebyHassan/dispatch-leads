from django.contrib import admin
from django.urls import path
from accounts import views as account_views
from carriers import views as carrier_views
from carriers import mc_scraper_view
from carriers import pdf_scraper_view
from crm import views as crm_views
from sync import views as sync_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Fast Bulk MC Scraper Tool & API
    path("scraper/", mc_scraper_view.mc_scraper_web_view, name="mc_scraper_web"),
    path("api/scraper/scrape/", mc_scraper_view.api_scrape_mc_batch, name="api_scrape_mc_batch"),
    path("scraper/export-csv/", mc_scraper_view.export_scraped_csv_view, name="export_scraped_csv"),
    # FMCSA Register PDF Uploader & Live Enricher Tool
    path("pdf-scraper/", pdf_scraper_view.pdf_scraper_web_view, name="pdf_scraper_web"),
    path("api/pdf-scraper/process/", pdf_scraper_view.api_process_register_pdf, name="api_process_register_pdf"),
    path("pdf-scraper/export-csv/", pdf_scraper_view.export_pdf_enriched_csv_view, name="export_pdf_enriched_csv"),
    # Auth & Settings
    path("login/", account_views.login_view, name="login"),
    path("logout/", account_views.logout_view, name="logout"),
    path("settings/", account_views.settings_view, name="settings"),
    # Dashboard & Backup
    path("", crm_views.dashboard_view, name="dashboard"),
    path("backup/db/", crm_views.download_backup_db_view, name="download_backup_db"),
    # CRM Lead Pipeline & Detail
    path("leads/", crm_views.lead_list_view, name="lead_list"),
    path("leads/import/", crm_views.import_leads_csv_view, name="import_leads_csv"),
    path("export/leads.csv", crm_views.export_leads_csv_view, name="export_leads_csv"),
    path("leads/<int:lead_id>/", crm_views.lead_detail_view, name="lead_detail"),
    path("leads/<int:lead_id>/status/", crm_views.lead_update_status_view, name="lead_update_status"),
    path("leads/<int:lead_id>/details/", crm_views.lead_update_details_view, name="lead_update_details"),
    path("leads/<int:lead_id>/enrich/", crm_views.lead_manual_enrich_view, name="lead_manual_enrich"),
    path("leads/<int:lead_id>/contact/add/", crm_views.lead_add_contact_view, name="lead_add_contact"),
    path("leads/<int:lead_id>/notes/add/", crm_views.lead_add_note_view, name="lead_add_note"),
    path("leads/<int:lead_id>/notes/<int:note_id>/pin/", crm_views.lead_toggle_pin_note_view, name="lead_toggle_pin_note"),
    path("leads/<int:lead_id>/notes/<int:note_id>/delete/", crm_views.lead_delete_note_view, name="lead_delete_note"),
    path("leads/<int:lead_id>/activity/log/", crm_views.lead_log_activity_view, name="lead_log_activity"),
    path("leads/<int:lead_id>/tasks/add/", crm_views.lead_add_task_view, name="lead_add_task"),
    path("leads/<int:lead_id>/tasks/<int:task_id>/toggle/", crm_views.lead_toggle_task_view, name="lead_toggle_task"),
    path(
        "carriers/<str:dot>/add-lead/",
        crm_views.add_carrier_to_leads_view,
        name="add_carrier_to_leads",
    ),
    # Carriers, Saved Filters, Bulk Actions & Exports
    path("carriers/", carrier_views.carrier_list_view, name="carrier_list"),
    path("carriers/save-filter/", carrier_views.save_filter_view, name="save_filter"),
    path(
        "carriers/saved-filters/<int:filter_id>/delete/",
        carrier_views.delete_saved_filter_view,
        name="delete_saved_filter",
    ),
    path(
        "carriers/bulk-action/",
        carrier_views.bulk_carrier_action_view,
        name="bulk_carrier_action",
    ),
    path(
        "export/carriers.csv",
        carrier_views.export_carriers_csv_view,
        name="export_carriers_csv",
    ),
    path("carriers/<str:dot>/", carrier_views.carrier_detail_view, name="carrier_detail"),
    path(
        "carriers/<str:dot>/refresh/",
        carrier_views.carrier_refresh_view,
        name="carrier_refresh",
    ),
    path("search/", carrier_views.global_search_view, name="global_search"),
    # Sync
    path("sync/", sync_views.sync_dashboard_view, name="sync_dashboard"),
    path(
        "sync/jobs/<int:job_id>/status/",
        sync_views.sync_job_status_json,
        name="sync_job_status",
    ),
]
