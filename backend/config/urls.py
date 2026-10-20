"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# backend/config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.urls import re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('accounts.urls')),
    path('api/', include('payroll.urls')),
    path('api/', include('workforce.urls')),
    path('api/', include('assistant.urls')),
]

if settings.DEBUG:
    # Only profile photos are served publicly (development only). Employee documents
    # are private and are streamed through an authenticated API endpoint instead.
    urlpatterns += [
        re_path(r'^media/(?P<path>profile_photos/.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
