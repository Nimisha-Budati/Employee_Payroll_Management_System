from django.contrib import admin

from .models import OvertimeRecord, Shift, ShiftAssignment

admin.site.register(Shift)
admin.site.register(ShiftAssignment)
admin.site.register(OvertimeRecord)
