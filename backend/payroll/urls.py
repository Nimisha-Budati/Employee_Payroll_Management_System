from django.urls import path

from . import analytics, dashboard, excel, variance, views

urlpatterns = [
    path('payroll/salary-structures/', views.salary_structure_list, name='salary-structure-list'),
    path('payroll/salary-structures/<int:employee_pk>/', views.salary_structure_detail, name='salary-structure-detail'),
    path('payroll/my-salary-structure/', views.my_salary_structure, name='my-salary-structure'),
    path('payroll/payslips/', views.payslip_list, name='payslip-list'),
    path('payroll/payslips/<int:pk>/', views.payslip_detail, name='payslip-detail'),
    path('payroll/payslips/<int:pk>/recalculate/', views.payslip_recalculate, name='payslip-recalculate'),
    path('payroll/payslips/<int:pk>/pdf/', views.payslip_pdf, name='payslip-pdf'),
    path('payroll/run/', views.payroll_run, name='payroll-run'),
    path('payroll/finalize/', views.payroll_finalize, name='payroll-finalize'),
    path('payroll/variance/', variance.payroll_variance, name='payroll-variance'),
    path('payroll/variance/review/', variance.payroll_variance_review, name='payroll-variance-review'),
    path('reports/analytics/', analytics.analytics_report, name='analytics-report'),
    path('payroll/export/', views.payroll_export, name='payroll-export'),
    path('payroll/reports/', views.payroll_reports, name='payroll-reports'),
    path('reports/excel/<str:kind>/', excel.excel_report, name='excel-report'),
    path('dashboard/admin/', dashboard.admin_dashboard, name='dashboard-admin'),
    path('dashboard/employee/', dashboard.employee_dashboard, name='dashboard-employee'),
]
