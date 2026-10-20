from django.contrib import admin

from .models import Payslip, SalaryStructure

admin.site.register(SalaryStructure)
admin.site.register(Payslip)
