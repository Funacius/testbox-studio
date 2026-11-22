"""Create a browser only when an explicitly invoked runner requests it."""

from selenium import webdriver


def create_browser(name: str, site: dict, headless: bool = False):
    if name == "chrome":
        options = webdriver.ChromeOptions()
        constructor = webdriver.Chrome
    elif name == "edge":
        options = webdriver.EdgeOptions()
        constructor = webdriver.Edge
    else:
        raise ValueError(f"Unsupported browser: {name}")
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-notifications")
    driver = constructor(options=options)
    try:
        driver.set_page_load_timeout(site.get("page_load_timeout", 30))
        driver.set_window_size(*site.get("window", [1440, 900]))
        driver.implicitly_wait(0)
    except Exception:
        driver.quit()
        raise
    return driver
