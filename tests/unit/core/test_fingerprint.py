"""Tests for device fingerprinting."""

from django.test import RequestFactory, TestCase

from django_smart_ratelimit.key_functions import (
    get_device_fingerprint_key as device_fingerprint_key,
)
from django_smart_ratelimit.utils import get_device_fingerprint_key


class DeviceFingerprintTests(TestCase):
    """Tests for device fingerprinting."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_device_fingerprint_key_generation(self):
        """Test that the device fingerprint key is generated correctly with the expected prefix and length."""
        request = self.factory.get("/")
        request.META["HTTP_USER_AGENT"] = "TestAgent"
        request.META["HTTP_ACCEPT_LANGUAGE"] = "en-US"

        key = device_fingerprint_key(request)
        assert key.startswith("device:")
        assert len(key) == 7 + 16  # device: + 16 chars hash

    def test_get_device_fingerprint_key_alias(self):
        """Test that get_device_fingerprint_key is an alias for device_fingerprint_key."""
        request = self.factory.get("/")
        request.META["HTTP_USER_AGENT"] = "TestAgent"

        key1 = device_fingerprint_key(request)
        key2 = get_device_fingerprint_key(request)

        assert key1 == key2

    def test_fingerprint_consistency(self):
        """Test that the same request details generate the same fingerprint."""
        request1 = self.factory.get("/")
        request1.META["HTTP_USER_AGENT"] = "TestAgent"

        request2 = self.factory.get("/")
        request2.META["HTTP_USER_AGENT"] = "TestAgent"

        assert device_fingerprint_key(request1) == device_fingerprint_key(request2)

    def test_fingerprint_difference(self):
        """Test that different request details generate different fingerprints."""
        request1 = self.factory.get("/")
        request1.META["HTTP_USER_AGENT"] = "TestAgent1"

        request2 = self.factory.get("/")
        request2.META["HTTP_USER_AGENT"] = "TestAgent2"

        assert device_fingerprint_key(request1) != device_fingerprint_key(request2)
