"""Plugin system for backend discovery."""

import importlib.metadata
import logging
from typing import Any, Dict, Type, Union

from django_smart_ratelimit.backends.base import BaseBackend

logger = logging.getLogger(__name__)


def discover_plugins() -> Dict[str, Type[BaseBackend]]:
    """Discover backend plugins via entry points."""
    plugins: Dict[str, Type[BaseBackend]] = {}

    try:
        entry_points = importlib.metadata.entry_points()

        # Python 3.10+ and 3.9 have different APIs
        backend_eps: Any
        if hasattr(entry_points, "select"):
            # Python 3.10+
            backend_eps = entry_points.select(group="django_smart_ratelimit.backends")
        else:
            # Python 3.9 - dictionary-like behavior
            backend_eps = getattr(entry_points, "get", lambda g, d: d)(
                "django_smart_ratelimit.backends", []
            )

        for ep in backend_eps:
            try:
                plugins[ep.name] = ep.load()
            except Exception as e:
                logger.warning(f"Failed to load plugin {ep.name}: {e}")

    except Exception as e:
        logger.warning(f"Plugin discovery failed: {e}")

    return plugins


def get_all_backends() -> Dict[str, Union[str, Type[BaseBackend]]]:
    """Get all available backends (built-in + plugins).

    Returns a dict where built-in backends are import path strings,
    and plugin backends are actual classes.
    """
    # Import here to avoid circular dependencies
    from django_smart_ratelimit.backends.factory import BUILTIN_BACKENDS

    backends: Dict[str, Union[str, Type[BaseBackend]]] = dict(BUILTIN_BACKENDS)
    backends.update(discover_plugins())

    return backends
