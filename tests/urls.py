"""
Test URLs for django-smart-ratelimit.

This file contains URL patterns used in tests.
"""

from django.urls import path
from django.http import HttpResponse

def test_view(request):
    return HttpResponse('OK')

urlpatterns = [
    path('test/', test_view, name='test'),
]
