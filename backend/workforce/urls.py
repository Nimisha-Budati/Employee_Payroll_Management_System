from django.urls import path

from . import views

urlpatterns = [
    path('shifts/', views.shift_list_create, name='shift-list-create'),
    path('shifts/my/', views.my_shift, name='my-shift'),
    path('shifts/assignments/', views.assignment_list_create, name='shift-assignment-list-create'),
    path('shifts/assignments/<int:pk>/', views.assignment_detail, name='shift-assignment-detail'),
    path('shifts/<int:pk>/', views.shift_detail, name='shift-detail'),
    path('overtime/', views.overtime_list_create, name='overtime-list-create'),
    path('overtime/generate/', views.overtime_generate, name='overtime-generate'),
    path('overtime/<int:pk>/', views.overtime_detail, name='overtime-detail'),
    path('overtime/<int:pk>/review/', views.overtime_review, name='overtime-review'),
]
