import unittest

from automation.locators import build_library, library_rows
from automation.schema import checked_step, locator, new_step


class LocatorTests(unittest.TestCase):
    def test_library_accepts_explicit_aliases_and_existing_selenium_locator_pairs(self):
        library = {"username": ["id", "username"], "submit": {"by": "css selector", "value": "button[type=submit]"}}
        rows = library_rows(library)
        rebuilt = build_library(rows)
        self.assertEqual(locator("@username", rebuilt), ("id", "username"))
        self.assertEqual(locator("@submit", rebuilt), ("css selector", "button[type=submit]"))

    def test_bad_alias_and_step_ids_are_rejected(self):
        for rows in ([{"Name": "x", "By": "css", "Selector": "#x"}] * 2,
                     [{"Name": "@x", "By": "css", "Selector": "#x"}],
                     [{"Name": "x", "By": "unknown", "Selector": "#x"}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                build_library(rows)
        for name in ("../../file", "/absolute", "x\\y", ""):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Step ID"):
                checked_step(new_step("open", id=name, target="http://example.test"))
