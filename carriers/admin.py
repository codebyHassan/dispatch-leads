from django.contrib import admin
from .models import Carrier, CarrierChange, SavedFilter, FilterAlert


@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = (
        "dot_number",
        "mc_number",
        "legal_name",
        "state",
        "power_units",
        "authority_status",
        "authority_grant_date",
        "phone_e164",
    )
    search_fields = ("dot_number", "mc_number", "legal_name", "dba_name", "phone_e164")
    list_filter = ("authority_status", "state", "safety_rating", "insurance_on_file")


admin.site.register(CarrierChange)
admin.site.register(SavedFilter)
admin.site.register(FilterAlert)
