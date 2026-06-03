# Geographic Rate Limiting

`django-smart-ratelimit` can bucket and limit requests by the client's
country, resolved from the request IP. This is useful for applying different
quotas per region, or for keying a single shared limit by country.

Geolocation is a thin provider abstraction over MaxMind's GeoIP2/GeoLite2
databases. It is entirely optional: without the `geoip2` package and a
configured database, country resolution returns `None` (`"unknown"`) and the
API still imports and runs, so you can leave the calls in your code
unconditionally.

The public API lives in `django_smart_ratelimit.geo`.

## Installation

Install the optional `geoip` extra, which pulls in `geoip2`:

```bash
pip install "django-smart-ratelimit[geoip]"
```

You also need a country (or city) database in MaxMind's `.mmdb` format.
Download a free **GeoLite2-City** or **GeoLite2-Country** database from MaxMind
(a free account is required), or use a commercial GeoIP2 database. Both are
read with the same `geoip2.database.Reader`.

## Configuration

Point the library at your `.mmdb` file with the `RATELIMIT_GEOIP_PATH`
setting:

```python
# settings.py
RATELIMIT_GEOIP_PATH = "/var/lib/GeoIP/GeoLite2-City.mmdb"
```

When this setting is present and loadable, the library uses a
`MaxMindProvider`. When it is unset (or the file/package is missing), it falls
back to a `NullGeoProvider` that resolves nothing. The provider is resolved
once and cached, so the database is opened a single time per process.

## Keying requests by country

`geo_key` is a key function suitable for the decorator's `key` argument. It
returns `geo:<CC>` using the ISO 3166-1 alpha-2 country code (e.g. `geo:US`),
or `geo:unknown` when the country cannot be resolved.

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.geo import geo_key


@rate_limit(key=geo_key, rate="1000/h")
def public_api(request):
    ...
```

All requests from the same country share one bucket. Note that this is a
single global limit per country, not a per-user limit; combine it with a
narrower key if you want per-client limits within a region.

## Resolving the country directly

If you only need the country code, call `get_country`. It accepts either a
request object or a raw IP string and returns the ISO code or `None`:

```python
from django_smart_ratelimit.geo import get_country

get_country(request)       # -> "US" (or None)
get_country("8.8.8.8")     # -> "US" (or None)
```

## Per-country rate selection

`get_rate_for_country` picks a rate string for a country from a mapping,
falling back to a default. The mapping is keyed by ISO code and maps to rate
strings like `"1000/h"`:

```python
from django_smart_ratelimit.geo import get_country, get_rate_for_country

COUNTRY_RATES = {
    "US": "1000/h",
    "CN": "100/h",
    "*": "500/h",   # wildcard: any country not listed above
}


def country_rate(request):
    country = get_country(request)
    return get_rate_for_country(country, COUNTRY_RATES, default_rate="200/h")
```

The lookup rules are:

- If `country` is set and present in the mapping, its rate is returned.
- Otherwise, if the mapping contains a `"*"` entry, that wildcard rate is used.
- Otherwise, `default_rate` is returned.

So with the mapping above, `"DE"` resolves to the wildcard `"500/h"`, while an
unknown country (`None`) with a mapping that has no `"*"` falls through to
`default_rate`.

You can feed this into the decorator by computing the rate at request time —
for example by composing `geo_key` for the key and a small wrapper that selects
the rate, or by enforcing the limit yourself in a view using your preferred
backend.

## The provider abstraction

Country resolution goes through a `GeoProvider`:

```python
from django_smart_ratelimit.geo import GeoProvider, GeoLocation


class GeoProvider:
    def lookup(self, ip: str) -> GeoLocation: ...
```

`GeoLocation` is a dataclass with `country`, `region`, and `city` fields, any
of which may be `None`:

```python
GeoLocation(country="US", region="CA", city="Mountain View")
```

Two implementations ship with the library:

- **`MaxMindProvider(db_path)`** — opens the `.mmdb` at `db_path` and looks up
  city/country data via `geoip2`. Constructing it raises
  `django.core.exceptions.ImproperlyConfigured` if `geoip2` is not installed.
  Any failed or invalid lookup returns an empty `GeoLocation()` rather than
  raising.
- **`NullGeoProvider`** — always returns an empty `GeoLocation()`. This is the
  fallback when `RATELIMIT_GEOIP_PATH` is unset, the database cannot be loaded,
  or `geoip2` is missing. With it, `get_country` returns `None` and `geo_key`
  returns `geo:unknown`.

`get_geo_provider()` returns the active, cached provider:

```python
from django_smart_ratelimit.geo import get_geo_provider

provider = get_geo_provider()   # MaxMindProvider or NullGeoProvider
```

## Overriding the provider (tests)

Use `set_geo_provider` to swap in your own provider, which is handy for tests
that should not depend on a real database. Pass `None` to reset back to the
cached default.

```python
from django_smart_ratelimit.geo import (
    GeoLocation,
    GeoProvider,
    geo_key,
    set_geo_provider,
)


class FakeGeo(GeoProvider):
    def lookup(self, ip):
        return GeoLocation(country="CN" if ip.startswith("1.") else "US")


def test_geo_key():
    set_geo_provider(FakeGeo())
    try:
        assert geo_key(make_request(ip="8.8.8.8")) == "geo:US"
        assert geo_key(make_request(ip="1.2.3.4")) == "geo:CN"
    finally:
        set_geo_provider(None)   # reset the cached provider
```

## Notes

- Country resolution depends on the client IP. The IP is taken from the same
  trusted-proxy / forwarded-header logic as the rest of the library, so make
  sure `RATELIMIT_TRUSTED_PROXIES` / `RATELIMIT_TRUST_FORWARDED_HEADERS` are
  configured correctly behind a proxy or CDN. See
  [Configuration](configuration.md).
- GeoIP lookups are best-effort: private, reserved, or unrecognized addresses
  resolve to `unknown`, and your limits should treat that bucket sensibly.
