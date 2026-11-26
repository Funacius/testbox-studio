"""Reuse an owned Chromium process while isolating each case's browsing state."""

import json
from urllib.parse import urlsplit


def origin(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host:
        host = "[" + host + "]"
    port = parts.port
    suffix = f":{port}" if port and port != (443 if parts.scheme == "https" else 80) else ""
    return parts.scheme + "://" + host + suffix


def remember_origins(driver):
    from selenium.common.exceptions import NoAlertPresentException
    # Reading an unrelated log while an alert is open can trigger WebDriver's
    # prompt policy. Leave those events queued until the author handles it.
    try:
        driver.switch_to.alert
        return
    except NoAlertPresentException:
        pass
    origins = getattr(driver, "_testbox_origins", set())
    for entry in driver.get_log("performance"):
        message = json.loads(entry["message"])["message"]
        if message.get("method", "").lower() == "tracing.bufferusage" and message.get("params", {}).get("error"):
            raise ValueError("Isolation origin log overflowed; use a fresh browser profile")
        params = message.get("params", {})
        urls = [params.get("request", {}).get("url", ""), params.get("response", {}).get("url", ""),
                params.get("redirectResponse", {}).get("url", ""), params.get("frame", {}).get("url", "")]
        for url in urls:
            candidate = origin(url)
            if candidate:
                origins.add(candidate)
    candidate = origin(driver.current_url)
    if candidate:
        origins.add(candidate)
    driver._testbox_origins = origins


def reset_state(driver, settings, headless):
    from selenium.common.exceptions import NoAlertPresentException
    try:
        driver.switch_to.alert.dismiss()
    except NoAlertPresentException:
        pass
    handles = driver.window_handles
    for handle in handles:
        driver.switch_to.window(handle)
        driver.switch_to.default_content()
        remember_origins(driver)
    # A new top-level browsing context discards sessionStorage for all old
    # origins, including contexts that are no longer the current document.
    driver.switch_to.new_window("tab")
    fresh = driver.current_window_handle
    for handle in handles:
        driver.switch_to.window(handle)
        driver.close()
    driver.switch_to.window(fresh)
    driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
    driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    for site_origin in sorted(getattr(driver, "_testbox_origins", set())):
        driver.execute_cdp_cmd("Storage.clearDataForOrigin", {"origin": site_origin, "storageTypes": "all"})
    driver._testbox_origins = set()
    if headless:
        width, height = settings.get("window", [1440, 900])
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})


def owned_reused_browser(drivers, name, settings, headless):
    from gradebook.browser import close_browser, create_browser
    driver = drivers.get(name)
    if driver is not None:
        try:
            if not driver.window_handles:
                raise ValueError("The owned browser was closed")
            reset_state(driver, settings, headless)
            driver._testbox_isolation = "reused process, new tab; global cookies/cache and observed-origin storage cleared"
            return driver
        except Exception:
            # If the session was closed or a reset cannot be proven, discard its
            # entire temporary profile before starting this case.
            try:
                close_browser(driver)
            except Exception:
                pass
            drivers.pop(name, None)
    driver = create_browser(name, {**settings, "isolation_logging": True}, headless)
    driver._testbox_origins = set()
    driver._testbox_isolation = "fresh temporary profile"
    drivers[name] = driver
    return driver
