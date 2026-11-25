"""Bounded, read-only connection checks before browser automation starts."""

import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def checked_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("Project settings must be an object")
    for key in ("variables", "locators", "environments"):
        if not isinstance(settings.get(key, {}), dict):
            raise ValueError(f"{key} must be an object")
    if not isinstance(settings.get("base_url", ""), str):
        raise ValueError("Base URL must be text")
    window = settings.get("window", [1440, 900])
    if not isinstance(window, list) or len(window) != 2 or any(type(v) is not int or not 200 <= v <= 8192 for v in window):
        raise ValueError("Window must contain a width and height between 200 and 8192 pixels")
    for key, default, lower, upper in (("timeout", 15, 0, 600), ("command_timeout", 60, 0, 600),
                                        ("page_load_timeout", 30, 0, 600), ("slow_ms", 0, -1, 10000)):
        value = settings.get(key, default)
        try:
            valid = not isinstance(value, bool) and math.isfinite(float(value)) and lower < float(value) <= upper
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError(f"{key} must be a number greater than {lower} and at most {upper}")
    for key in ("highlight", "check_connection"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"{key} must be true or false")
    return settings


def website_status(base_url, timeout=3):
    """Probe the origin, not a potentially state-changing testcase URL."""
    if not base_url:
        return "No base URL: absolute step URLs will be checked by the browser."
    parts = urlsplit(base_url)
    if parts.scheme in {"file", "data"}:
        return "Local URL configured; browser will open it when Run starts."
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Base URL must include http:// or https://")
    if any(character.isspace() for character in parts.netloc):
        raise ValueError("The website hostname cannot contain spaces")
    origin = f"{parts.scheme}://{parts.netloc}/"
    try:
        request = Request(origin, headers={"User-Agent": "Testbox-Studio-Readiness"})
        with urlopen(request, timeout=timeout) as response:
            code = response.status
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if code >= 500:
            raise ValueError(f"Website returned HTTP {code}: {origin}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        hint = "Start the local website/service and check its port."
        if parts.hostname in {"127.0.0.1", "localhost"} and parts.port == 9501:
            hint = "Open Docker Desktop, then run: docker start pro2-moodle"
        raise ValueError(f"Cannot reach {origin}\n{hint}\nDetails: {exc}") from exc
    return f"Website reachable: HTTP {code} at {origin}"
