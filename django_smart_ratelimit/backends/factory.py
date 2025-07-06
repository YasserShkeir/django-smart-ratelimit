"""Backend factory for Django Smart Ratelimit."""

import importlib
import logging
from typing import Any, Dict, Type

from django.conf import settings

from .base import BaseBackend

logger = logging.getLogger(__name__)


class BackendFactory:
    """Factory class for creating backend instances."""

    _backend_cache: Dict[str, Type[BaseBackend]] = {}

    @classmethod
    def get_backend_class(cls, backend_path: str) -> Type[BaseBackend]:
        """
        Get backend class from dotted path.

        Args:
            backend_path: Dotted path to backend class

        Returns:
            Backend class

        Raises:
            ImportError: If backend cannot be imported
            AttributeError: If backend class not found
        """
        if backend_path in cls._backend_cache:
            return cls._backend_cache[backend_path]

        try:
            module_path, class_name = backend_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            backend_class = getattr(module, class_name)

            if not issubclass(backend_class, BaseBackend):
                raise TypeError(f"Backend {backend_path} must inherit from BaseBackend")

            cls._backend_cache[backend_path] = backend_class
            return backend_class

        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to import backend {backend_path}: {e}")
            raise

    @classmethod
    def create_backend(cls, backend_path: str, **kwargs: Any) -> BaseBackend:
        """
        Create backend instance from dotted path.

        Args:
            backend_path: Dotted path to backend class
            **kwargs: Additional arguments for backend initialization

        Returns:
            Backend instance

        Raises:
            ImportError: If backend cannot be imported
            AttributeError: If backend class not found
        """
        backend_class = cls.get_backend_class(backend_path)
        return backend_class(**kwargs)

    @classmethod
    def create_from_settings(cls) -> BaseBackend:
        """
        Create backend instance from Django settings.

        Returns:
            Backend instance configured from settings

        Raises:
            ImportError: If backend cannot be imported
            AttributeError: If backend class not found
        """
        backend_path = getattr(settings, "RATELIMIT_BACKEND", None)
        if not backend_path:
            # Default to Redis backend for backward compatibility
            backend_path = "django_smart_ratelimit.backends.redis_backend.RedisBackend"

        backend_config = getattr(settings, "RATELIMIT_BACKEND_CONFIG", {})
        return cls.create_backend(backend_path, **backend_config)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear backend class cache."""
        cls._backend_cache.clear()
