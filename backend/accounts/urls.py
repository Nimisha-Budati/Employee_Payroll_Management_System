from django.urls import path
from .views import attendance_history, attendance_list, attendance_mark, attendance_settings, attendance_status, change_password, document_delete, document_list_create, document_review, employee_detail, employee_list_create, holiday_detail, holiday_list_create, login_user, logout_user, my_profile, register, request_password_reset, reset_password, verify_password_reset, leave_list_create, leave_update_status, wfh_detail, wfh_list_create

urlpatterns = [
    path('register/', register),
    path('login/', login_user),
    path('logout/', logout_user),
    path('password/forgot/', request_password_reset),
    path('password/verify-otp/', verify_password_reset),
    path('password/reset/', reset_password),
    path('password/change/', change_password),
    path('employees/', employee_list_create, name='employee-list-create'),
    path('employees/<int:pk>/', employee_detail, name='employee-detail'),
    path('leaves/', leave_list_create, name='leave-list-create'),
    path('leaves/<int:pk>/status/', leave_update_status, name='leave-update-status'),
    path('documents/', document_list_create, name='document-list-create'),
    path('documents/<int:pk>/', document_delete, name='document-delete'),
    path('documents/<int:pk>/review/', document_review, name='document-review'),
    path('profile/', my_profile, name='my-profile'),
    path('holidays/', holiday_list_create, name='holiday-list-create'),
    path('holidays/<int:pk>/', holiday_detail, name='holiday-detail'),
    path('attendance/settings/', attendance_settings, name='attendance-settings'),
    path('attendance/status/', attendance_status, name='attendance-status'),
    path('attendance/history/', attendance_history, name='attendance-history'),
    path('attendance/<str:action>/', attendance_mark, name='attendance-mark'),
    path('attendance/', attendance_list, name='attendance-list'),
    path('wfh/', wfh_list_create, name='wfh-list-create'),
    path('wfh/<int:pk>/', wfh_detail, name='wfh-detail'),
]
