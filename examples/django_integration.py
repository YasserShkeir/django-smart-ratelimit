#!/usr/bin/env python3
"""
Django Integration Examples

This demonstrates how to integrate django-smart-ratelimit into
various Django application patterns and frameworks.
"""

# Example 1: Django REST Framework Integration
"""
# serializers.py
from rest_framework import serializers
from django_smart_ratelimit import rate_limit

class APIKeySerializer(serializers.Serializer):
    api_key = serializers.CharField(max_length=64)

    def validate_api_key(self, value):
        # Custom validation logic
        if not self.is_valid_api_key(value):
            raise serializers.ValidationError("Invalid API key")
        return value

# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django_smart_ratelimit import rate_limit

class PublicAPIView(APIView):
    '''Public API endpoints with basic rate limiting.'''

    @rate_limit(key='ip', rate='100/h')
    def get(self, request):
        return Response({'message': 'Public data'})

    @rate_limit(key='ip', rate='10/h')
    def post(self, request):
        # Process POST data
        return Response({'status': 'created'}, status=status.HTTP_201_CREATED)

class AuthenticatedAPIView(APIView):
    '''API endpoints for authenticated users.'''

    def get_rate_limit_key(self, request):
        if request.user.is_authenticated:
            return f"user:{request.user.id}"
        return f"ip:{request.META.get('REMOTE_ADDR')}"

    @rate_limit(key=get_rate_limit_key, rate='1000/h')
    def get(self, request):
        return Response({
            'message': 'Authenticated data',
            'user_id': request.user.id
        })

class TenantAPIView(APIView):
    '''Multi-tenant API with tenant-specific rate limiting.'''

    def get_tenant_key(self, request):
        tenant_id = request.headers.get('X-Tenant-ID')
        if tenant_id:
            return f"tenant:{tenant_id}"
        return f"user:{request.user.id}" if request.user.is_authenticated else f"ip:{request.META.get('REMOTE_ADDR')}"

    @rate_limit(key=get_tenant_key, rate='10000/h')
    def get(self, request):
        tenant_id = request.headers.get('X-Tenant-ID')
        return Response({
            'message': 'Tenant data',
            'tenant_id': tenant_id
        })

# Custom rate limit exception for DRF
from rest_framework.exceptions import Throttled

class RateLimitExceeded(Throttled):
    status_code = 429
    default_detail = 'Request rate limit exceeded.'
    default_code = 'throttled'

    def __init__(self, detail=None, retry_after=None):
        if retry_after:
            self.detail = f"{detail} Retry after {retry_after} seconds."
        else:
            self.detail = detail or self.default_detail

# Custom rate limit response for DRF
def drf_rate_limit_response(request):
    raise RateLimitExceeded(
        detail="API rate limit exceeded. Please slow down your requests.",
        retry_after=60
    )

@rate_limit(key='ip', rate='5/m', block=drf_rate_limit_response)
def rate_limited_drf_view(request):
    return Response({'message': 'Success'})
"""


# Example 2: Django Channels (WebSocket) Integration
"""
# consumers.py
import json
from channels.generic.websocket import WebsocketConsumer
from django_smart_ratelimit.backends import get_backend

class RateLimitedWebSocketConsumer(WebsocketConsumer):
    '''WebSocket consumer with rate limiting.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rate_limit_backend = get_backend('redis')

    def connect(self):
        # Rate limit WebSocket connections
        client_ip = self.scope['client'][0]
        if self.is_rate_limited(f"ws_connect:{client_ip}", 10, 60):  # 10 connections per minute
            self.close(code=1008)  # Policy violation
            return

        self.accept()

    def receive(self, text_data):
        # Rate limit WebSocket messages
        client_ip = self.scope['client'][0]
        user_id = self.scope.get('user', {}).get('id', 'anonymous')

        if self.is_rate_limited(f"ws_message:{user_id}:{client_ip}", 60, 60):  # 60 messages per minute
            self.send(text_data=json.dumps({
                'error': 'Message rate limit exceeded'
            }))
            return

        try:
            data = json.loads(text_data)
            # Process message
            self.send(text_data=json.dumps({
                'status': 'received',
                'message': data
            }))
        except json.JSONDecodeError:
            self.send(text_data=json.dumps({
                'error': 'Invalid JSON'
            }))

    def is_rate_limited(self, key, limit, period):
        '''Check if action is rate limited.'''
        return self.rate_limit_backend.is_rate_limited(key, limit, period)

class ChatConsumer(RateLimitedWebSocketConsumer):
    '''Chat consumer with message rate limiting.'''

    def receive(self, text_data):
        # Different rate limits for different message types
        data = json.loads(text_data)
        message_type = data.get('type', 'message')
        user_id = self.scope.get('user', {}).get('id', 'anonymous')

        rate_limits = {
            'message': (30, 60),      # 30 messages per minute
            'image': (5, 60),         # 5 images per minute
            'file': (2, 60),          # 2 files per minute
            'reaction': (100, 60),    # 100 reactions per minute
        }

        limit, period = rate_limits.get(message_type, (10, 60))

        if self.is_rate_limited(f"chat:{message_type}:{user_id}", limit, period):
            self.send(text_data=json.dumps({
                'error': f'{message_type.title()} rate limit exceeded'
            }))
            return

        # Process the message
        super().receive(text_data)
"""


# Example 3: Django Admin Integration
"""
# admin.py
from django.contrib import admin
from django.http import HttpResponse
from django_smart_ratelimit import rate_limit

class RateLimitedAdmin(admin.ModelAdmin):
    '''Admin interface with rate limiting for sensitive operations.'''

    @rate_limit(key='user', rate='10/h')
    def changelist_view(self, request, extra_context=None):
        # Rate limit bulk operations
        return super().changelist_view(request, extra_context)

    @rate_limit(key='user', rate='5/h')
    def delete_view(self, request, object_id, extra_context=None):
        # Rate limit deletions
        return super().delete_view(request, object_id, extra_context)

# Custom admin action with rate limiting
@rate_limit(key='user', rate='1/h')
def bulk_export_action(modeladmin, request, queryset):
    # Rate limit bulk exports (expensive operation)
    # Export logic here
    return HttpResponse("Export completed")

bulk_export_action.short_description = "Export selected items"

class MyModelAdmin(RateLimitedAdmin):
    actions = [bulk_export_action]
"""


# Example 4: Django Forms Integration
"""
# forms.py
from django import forms
from django.core.exceptions import ValidationError
from django_smart_ratelimit.backends import get_backend

class RateLimitedForm(forms.Form):
    '''Base form with rate limiting capabilities.'''

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.rate_limit_backend = get_backend('redis')

    def clean(self):
        cleaned_data = super().clean()

        if self.request:
            # Rate limit form submissions
            client_ip = self.request.META.get('REMOTE_ADDR')
            if self.rate_limit_backend.is_rate_limited(f"form_submit:{client_ip}", 10, 300):  # 10 per 5 minutes
                raise ValidationError("Too many form submissions. Please wait before trying again.")

        return cleaned_data

class ContactForm(RateLimitedForm):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    message = forms.CharField(widget=forms.Textarea)

    def clean(self):
        cleaned_data = super().clean()

        if self.request:
            # Additional rate limiting for contact forms
            email = cleaned_data.get('email')
            if email:
                email_key = f"contact_email:{email}"
                if self.rate_limit_backend.is_rate_limited(email_key, 3, 3600):  # 3 per hour per email
                    raise ValidationError("Too many messages from this email address.")

        return cleaned_data

class PasswordResetForm(RateLimitedForm):
    email = forms.EmailField()

    def clean_email(self):
        email = self.cleaned_data['email']

        if self.request:
            # Strict rate limiting for password resets
            client_ip = self.request.META.get('REMOTE_ADDR')
            email_key = f"password_reset:{email}"
            ip_key = f"password_reset_ip:{client_ip}"

            if (self.rate_limit_backend.is_rate_limited(email_key, 3, 3600) or  # 3 per hour per email
                self.rate_limit_backend.is_rate_limited(ip_key, 5, 3600)):      # 5 per hour per IP
                raise ValidationError("Too many password reset attempts. Please try again later.")

        return email
"""


# Example 5: Custom Middleware for Specific Patterns
"""
# middleware.py
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
from django_smart_ratelimit.backends import get_backend

class APIKeyRateLimitMiddleware(MiddlewareMixin):
    '''Rate limiting middleware based on API keys.'''

    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limit_backend = get_backend('redis')
        super().__init__(get_response)

    def process_request(self, request):
        # Only apply to API endpoints
        if not request.path.startswith('/api/'):
            return None

        api_key = request.headers.get('X-API-Key')
        if not api_key:
            # No API key, apply IP-based rate limiting
            key = f"no_api_key:{request.META.get('REMOTE_ADDR')}"
            limit = 10  # Very low limit for non-API key requests
            period = 3600
        else:
            # API key present, apply key-based rate limiting
            key = f"api_key:{api_key}"
            # Different limits based on API key tier (you'd look this up from your database)
            limit = self.get_api_key_limit(api_key)
            period = 3600

        if self.rate_limit_backend.is_rate_limited(key, limit, period):
            return HttpResponse(
                '{"error": "Rate limit exceeded"}',
                status=429,
                content_type='application/json'
            )

        return None

    def get_api_key_limit(self, api_key):
        # Look up API key tier and return appropriate limit
        # This would typically query your database
        api_key_limits = {
            'free': 100,
            'basic': 1000,
            'premium': 10000,
            'enterprise': 100000,
        }

        # Default to free tier if not found
        # In practice, you'd query your database here
        return api_key_limits.get('free', 100)

class GeographicRateLimitMiddleware(MiddlewareMixin):
    '''Rate limiting based on geographic location.'''

    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limit_backend = get_backend('redis')
        super().__init__(get_response)

    def process_request(self, request):
        # Get country from CloudFlare header (or use GeoIP library)
        country = request.META.get('HTTP_CF_IPCOUNTRY', 'unknown')
        client_ip = request.META.get('REMOTE_ADDR')

        # Different rate limits per country
        country_limits = {
            'US': 1000,
            'CA': 1000,
            'GB': 1000,
            'DE': 1000,
            'FR': 1000,
            'default': 100,  # Lower limit for other countries
        }

        limit = country_limits.get(country, country_limits['default'])
        key = f"geo:{country}:{client_ip}"

        if self.rate_limit_backend.is_rate_limited(key, limit, 3600):
            return HttpResponse(
                '{"error": "Geographic rate limit exceeded"}',
                status=429,
                content_type='application/json'
            )

        return None
"""


# Example 6: Celery Task Rate Limiting
"""
# tasks.py
from celery import shared_task
from django_smart_ratelimit.backends import get_backend

@shared_task
def rate_limited_task(user_id, task_data):
    '''Celery task with rate limiting.'''
    rate_limit_backend = get_backend('redis')

    # Rate limit task execution per user
    key = f"task_execution:{user_id}"
    if rate_limit_backend.is_rate_limited(key, 10, 60):  # 10 tasks per minute per user
        # Log the rate limit violation
        print(f"Task rate limit exceeded for user {user_id}")
        return {'error': 'Task rate limit exceeded'}

    # Execute the task
    result = process_task_data(task_data)
    return result

def process_task_data(data):
    # Actual task processing logic
    return {'status': 'completed', 'data': data}

# Rate limit task scheduling
def schedule_user_task(user_id, task_data):
    '''Schedule a task with rate limiting.'''
    rate_limit_backend = get_backend('redis')

    # Rate limit task scheduling
    schedule_key = f"task_schedule:{user_id}"
    if rate_limit_backend.is_rate_limited(schedule_key, 5, 300):  # 5 schedules per 5 minutes
        return {'error': 'Task scheduling rate limit exceeded'}

    # Schedule the task
    task_result = rate_limited_task.delay(user_id, task_data)
    return {'task_id': task_result.id}
"""


if __name__ == "__main__":
    print("Django Integration Examples")
    print("===========================")
    print("")
    print("This file contains examples of Django framework integrations:")
    print("1. Django REST Framework (DRF) integration")
    print("2. Django Channels (WebSocket) integration")
    print("3. Django Admin interface integration")
    print("4. Django Forms integration")
    print("5. Custom middleware patterns")
    print("6. Celery task rate limiting")
    print("")
    print("These examples show how to integrate rate limiting")
    print("into various Django application patterns and third-party packages.")
