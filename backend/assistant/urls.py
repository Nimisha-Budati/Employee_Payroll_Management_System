from django.urls import path

from . import views

urlpatterns = [
    path('ai/status/', views.ai_status, name='ai-status'),
    path('ai/conversations/', views.conversation_list_create, name='ai-conversation-list-create'),
    path('ai/conversations/<int:pk>/', views.conversation_detail, name='ai-conversation-detail'),
    path('ai/conversations/<int:pk>/messages/', views.message_create, name='ai-message-create'),
    path('ai/attendance-insights/', views.attendance_insights, name='ai-attendance-insights'),
    path('ai/attendance-insights/stats/', views.attendance_insight_stats, name='ai-attendance-insight-stats'),
    path('ai/knowledge/', views.knowledge, name='ai-knowledge'),
]
