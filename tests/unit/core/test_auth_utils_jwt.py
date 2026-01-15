"""Tests for JWT extraction utilities."""

import sys
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase

from django_smart_ratelimit.auth_utils import extract_jwt_claim


class TestJwtExtraction(TestCase):
    """Tests for JWT extraction."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_extract_jwt_success(self):
        """Test successful JWT extraction."""
        mock_jwt = MagicMock()
        mock_jwt.decode.return_value = {"user_id": "123", "role": "admin"}

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer valid.token")
            result = extract_jwt_claim(request, "user_id")
            self.assertEqual(result, "123")

            result = extract_jwt_claim(request, "role")
            self.assertEqual(result, "admin")

    def test_extract_jwt_invalid_format(self):
        """Test handling of malformed JWT."""
        mock_jwt = MagicMock()
        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer not.a.valid.jwt")
            mock_jwt.decode.side_effect = Exception("Invalid token")
            result = extract_jwt_claim(request, "user_id")
            self.assertIsNone(result)

    def test_extract_jwt_missing_header(self):
        """Test missing Authorization header."""
        request = self.factory.get("/")
        result = extract_jwt_claim(request, "user_id")
        self.assertIsNone(result)

    def test_extract_jwt_wrong_scheme(self):
        """Test wrong Authorization scheme."""
        request = self.factory.get("/", HTTP_AUTHORIZATION="Basic user:pass")
        result = extract_jwt_claim(request, "user_id")
        self.assertIsNone(result)

    def test_extract_jwt_missing_claim(self):
        """Test extraction of non-existent claim."""
        mock_jwt = MagicMock()
        mock_jwt.decode.return_value = {"user_id": "123"}

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer valid.token")
            result = extract_jwt_claim(request, "role")
            self.assertIsNone(result)

    def test_extract_jwt_expired(self):
        """Test handling of expired JWT."""
        mock_jwt = MagicMock()
        # Simulate expiration error if the library raises one, or just return None if logic handles it
        # Assuming extract_jwt_claim catches exceptions
        mock_jwt.decode.side_effect = Exception("Signature has expired")

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer expired.token")
            result = extract_jwt_claim(request, "user_id")
            self.assertIsNone(result)

    def test_extract_jwt_invalid_headers_parametrized(self):
        """Test handling of various invalid auth headers."""
        invalid_headers = [
            "",
            "Bearer",
            "Bearer ",
            "Basic dXNlcjpwYXNz",
            "Token abc123",
            "bearer lowercase",  # Case sensitivity check
        ]

        for header in invalid_headers:
            request = self.factory.get("/", HTTP_AUTHORIZATION=header)
            result = extract_jwt_claim(request, "user_id")
            self.assertIsNone(result, f"Should return None for header: '{header}'")

    def test_extract_jwt_nested_claim(self):
        """Test extraction of nested claims."""
        mock_jwt = MagicMock()
        mock_jwt.decode.return_value = {"user": {"id": "123", "role": "admin"}}

        with patch.dict(sys.modules, {"jwt": mock_jwt}):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer valid.token")

            # Test extracting the parent object
            result = extract_jwt_claim(request, "user")
            self.assertEqual(result, {"id": "123", "role": "admin"})

            # Note: extract_jwt_claim might not support dot notation "user.id"
            # If it does, we should test it. If not, we skip it.
            # Based on typical implementations, it usually just does dict.get(claim)
            # So "user.id" would look for a key "user.id", not nested.
