"""Create a browser only when an explicitly invoked runner requests it."""

import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.selenium_manager import SeleniumManager


def create_browser(name: str, site: dict, headless: bool = False):
    service = None
    if name == "chrome":
        options = webdriver.ChromeOptions()
        constructor = webdriver.Chrome
    elif name == "edge":
        options = webdriver.EdgeOptions()
        constructor = webdriver.Edge
    elif name == "opera":
        options = webdriver.ChromeOptions()
        binary = site.get("opera_binary") or os.environ.get("TESTBOX_OPERA_BINARY")
        if not binary:
            binary = str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Opera GX/opera.exe")
        if not Path(binary).is_file():
            raise ValueError("Opera GX binary not found; set TESTBOX_OPERA_BINARY or opera_binary in site settings")
        core = os.environ.get("TESTBOX_OPERA_CHROMIUM_VERSION") or site.get("opera_chromium_version")
        if not core:
            raise ValueError("Set opera_chromium_version to Opera GX's Chromium major version, not its Opera version")
        paths = SeleniumManager().binary_paths(["--browser", "chrome", "--browser-version", str(core),
                                               "--avoid-browser-download", "--timeout", "60"])
        options.binary_location = binary
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        service = Service(paths["driver_path"])
        constructor = webdriver.Chrome
    else:
        raise ValueError(f"Unsupported browser: {name}")
    # Moodle may keep loading optional assets after its form is interactive.
    # Page objects explicitly wait for the actual controls and saved state.
    options.page_load_strategy = site.get("page_load_strategy", "eager")
    # These preferences belong only to Selenium's fresh temporary profile.
    # Browser-owned password dialogs otherwise intercept native UI actions.
    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.password_manager_leak_detection": False,
    })
    if site.get("browser_logging") or site.get("isolation_logging"):
        logs = {}
        if site.get("browser_logging"):
            logs["browser"] = "ALL"
        if site.get("isolation_logging"):
            logs["performance"] = "ALL"
        options.set_capability("ms:loggingPrefs" if name == "edge" else "goog:loggingPrefs", logs)
    if site.get("browser_logging"):
        options.unhandled_prompt_behavior = "ignore"
    options.add_argument("--disable-features=PasswordLeakDetection" + (",BackForwardCache" if site.get("browser_logging") else ""))
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--disable-notifications")
    options.add_argument("--force-device-scale-factor=1")
    driver = constructor(options=options, **({"service": service} if service else {}))
    try:
        driver.command_executor.client_config.timeout = site.get("command_timeout", 60)
        driver.set_page_load_timeout(site.get("page_load_timeout", 30))
        driver.set_window_size(*site.get("window", [1440, 900]))
        if headless:
            width, height = site.get("window", [1440, 900])
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        if name == "opera" and not headless:
            window = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
            driver.execute_cdp_cmd("Browser.setWindowBounds", {
                "windowId": window["windowId"], "bounds": {"windowState": "normal"}})
            driver.execute_cdp_cmd("Page.bringToFront", {})
            driver.set_window_size(*site.get("window", [1440, 900]))
        driver.implicitly_wait(0)
    except Exception:
        driver.quit()
        raise
    return driver


def close_browser(driver) -> None:
    """Close the owned temporary browser before stopping its WebDriver service."""
    driver.command_executor.client_config.timeout = 5
    try:
        driver.execute_cdp_cmd("Browser.close", {})
    except Exception:
        # Closing the browser may close its debugging connection before reply.
        pass
    finally:
        driver.quit()
