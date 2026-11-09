from django.contrib import admin
from .models import Settings, SyncJob

admin.site.register(Settings)
admin.site.register(SyncJob)
