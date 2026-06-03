"""Geographic rate limiting (roadmap Phase 5.4).

A small provider abstraction over IP geolocation: a no-op default, and a MaxMind
GeoIP2 provider used when the optional ``geoip2`` package and a GeoLite2 database
are configured (``RATELIMIT_GEOIP_PATH``). Country resolution feeds the
``geo_key`` key function and per-country rate selection. Everything degrades
gracefully (country ``None`` / "unknown") when geolocation is unavailable.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class GeoLocation:
    """Resolved geo info for an IP (any field may be ``None``)."""

    country: Optional[str] = None  # ISO 3166-1 alpha-2, e.g. "US"
    region: Optional[str] = None
    city: Optional[str] = None


class GeoProvider:
    """Interface for IP -> :class:`GeoLocation` lookups."""

    def lookup(self, ip: str) -> GeoLocation:
        """Return the location for ``ip`` (empty GeoLocation if unknown)."""
        raise NotImplementedError


class NullGeoProvider(GeoProvider):
    """Fallback provider that resolves nothing (used when GeoIP is unconfigured)."""

    def lookup(self, ip: str) -> GeoLocation:
        """Always return an empty location."""
        return GeoLocation()


class MaxMindProvider(GeoProvider):
    """GeoIP2/GeoLite2 provider backed by the optional ``geoip2`` package."""

    def __init__(self, db_path: str) -> None:
        """Open the GeoLite2/GeoIP2 database at ``db_path``.

        Raises ImproperlyConfigured if ``geoip2`` is not installed.
        """
        try:
            import geoip2.database
        except ImportError as exc:  # pragma: no cover - optional dependency
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                "Geographic rate limiting requires the 'geoip2' package "
                "(pip install django-smart-ratelimit[geoip])."
            ) from exc
        self._reader = geoip2.database.Reader(db_path)

    def lookup(self, ip: str) -> GeoLocation:
        """Look up ``ip``; return an empty location on any lookup failure."""
        try:
            response = self._reader.city(ip)
            return GeoLocation(
                country=(response.country.iso_code or None),
                region=(
                    response.subdivisions.most_specific.iso_code
                    if response.subdivisions
                    else None
                ),
                city=(response.city.name or None),
            )
        except Exception:  # pragma: no cover - unknown/invalid IP
            return GeoLocation()


_provider: Optional[GeoProvider] = None


def get_geo_provider() -> GeoProvider:
    """Return the configured geo provider (cached).

    Uses :class:`MaxMindProvider` when ``RATELIMIT_GEOIP_PATH`` is set and
    loadable, otherwise the :class:`NullGeoProvider`.
    """
    global _provider
    if _provider is not None:
        return _provider

    db_path = None
    try:
        from .config import get_settings

        db_path = getattr(get_settings(), "geoip_path", None)
    except Exception:  # pragma: no cover - settings not ready
        db_path = None

    if db_path:
        try:
            _provider = MaxMindProvider(db_path)
            return _provider
        except Exception:  # pragma: no cover - bad path / missing dep
            pass
    _provider = NullGeoProvider()
    return _provider


def set_geo_provider(provider: Optional[GeoProvider]) -> None:
    """Override the geo provider (mainly for tests); ``None`` resets the cache."""
    global _provider
    _provider = provider


def _client_ip(request_or_ip: Any) -> str:
    if isinstance(request_or_ip, str):
        return request_or_ip
    from .key_functions import get_ip_key

    # get_ip_key returns "ip:<addr>"; strip the prefix for a raw IP.
    key = get_ip_key(request_or_ip)
    return key.split(":", 1)[1] if ":" in key else key


def get_country(request_or_ip: Any) -> Optional[str]:
    """Resolve the ISO country code for a request or raw IP, or ``None``."""
    ip = _client_ip(request_or_ip)
    return get_geo_provider().lookup(ip).country


def geo_key(request: Any, *args: Any, **kwargs: Any) -> str:
    """Key function: bucket a request by client country (``geo:<CC>``)."""
    return f"geo:{get_country(request) or 'unknown'}"


def get_rate_for_country(
    country: Optional[str], country_rates: Dict[str, str], default_rate: str
) -> str:
    """Return the configured rate for ``country``, else ``default_rate``.

    ``country_rates`` is a mapping of ISO code -> rate string, e.g.
    ``{"US": "1000/h", "CN": "100/h"}``. A special ``"*"`` entry, if present,
    overrides the default for any country not explicitly listed.
    """
    if country and country in country_rates:
        return country_rates[country]
    return country_rates.get("*", default_rate)
