from django.contrib import admin
from .models import Lead, Contact, Note, Activity, Task, Template, AuditLog

admin.site.register(Lead)
admin.site.register(Contact)
admin.site.register(Note)
admin.site.register(Activity)
admin.site.register(Task)
admin.site.register(Template)
admin.site.register(AuditLog)
