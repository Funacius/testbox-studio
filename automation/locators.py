"""Locator library validation and non-destructive browser inspection."""

from automation.schema import locator, resolve

DISPLAY_BY = {"css selector": "css", "link text": "link", "partial link text": "partial_link", "tag name": "tag", "class name": "class"}


def library_rows(library):
    rows = []
    for name in library:
        by, selector = locator("@" + name, library)
        rows.append(dict(Name=name, By=DISPLAY_BY.get(by, by), Selector=selector))
    return rows


def build_library(rows):
    library = {}
    for index, row in enumerate(rows, 1):
        name = row.get("Name", "").strip()
        if not name or name.startswith("@"):
            raise ValueError(f"Locator row {index}: enter an alias name without @")
        if name in library:
            raise ValueError(f"Duplicate locator alias: {name}")
        by = row.get("By", "").strip().lower()
        library[name] = {"by": by, "value": row.get("Selector", "")}
        locator("@" + name, library)
    return library


def probe_locator(driver, target, library, variables=None, highlight=True):
    values = variables or {}
    by, selector = locator(resolve(target, values), library)
    selector = resolve(selector, values)
    elements = driver.find_elements(by, selector)
    visible = [element for element in elements if element.is_displayed()]
    if highlight:
        driver.execute_script("for(const p of(window.__testboxOutlines||[])){try{p[0].style.outline=p[1]}catch(e){}}window.__testboxOutlines=[];")
        for element in visible:
            driver.execute_script("window.__testboxOutlines.push([arguments[0],arguments[0].style.outline]);arguments[0].style.outline='3px solid #ea8a23';", element)
        if visible:
            driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", visible[0])
    status = "NOT FOUND" if not elements else "HIDDEN" if not visible else "AMBIGUOUS" if len(visible) > 1 else "MATCH"
    return dict(status=status, total_matches=len(elements), visible_matches=len(visible),
                enabled_matches=sum(e.is_enabled() for e in visible),
                examples=[dict(tag=e.tag_name, id=e.get_attribute("id"), text=e.text[:180]) for e in visible[:5]])
