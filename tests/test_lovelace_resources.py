"""Regression checks for safe Lovelace resource auto-registration.

Run without a Home Assistant installation:
    python -m unittest discover -s tests -p "test_lovelace_resources.py"
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "heating_center" / "lovelace_resources.py"
)
RESOURCE_PATH = "/heating_center_assets/heating-center-card.js"


def load_registrar():
    homeassistant = types.ModuleType("homeassistant")
    homeassistant_core = types.ModuleType("homeassistant.core")
    homeassistant_core.HomeAssistant = type("HomeAssistant", (), {})
    spec = importlib.util.spec_from_file_location("heating_center_lovelace_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"homeassistant": homeassistant, "homeassistant.core": homeassistant_core},
    ):
        spec.loader.exec_module(module)
    return module.async_register_card_resource


class FakeResources:
    def __init__(self, stored=None, loaded=True):
        self.stored = list(stored or [])
        self.items = list(stored or []) if loaded else []
        self.loaded = loaded
        self.calls = []

    async def async_load(self):
        self.calls.append("load")
        self.items = list(self.stored)
        self.loaded = True

    def async_items(self):
        self.calls.append("items")
        assert self.loaded, "Read before stored resources loaded"
        return self.items

    async def async_create_item(self, data):
        self.calls.append("create")
        assert self.loaded, "Write before stored resources loaded"
        self.items.append({"id": "new", **data})

    async def async_update_item(self, item_id, data):
        self.calls.append("update")
        assert self.loaded
        index = next(i for i, r in enumerate(self.items) if r["id"] == item_id)
        self.items[index] = {**self.items[index], **data}


def hass_with(resources, mode="storage"):
    lovelace = types.SimpleNamespace(resource_mode=mode, resources=resources)
    return types.SimpleNamespace(data={"lovelace": lovelace})


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.register = load_registrar()

    async def test_creates_once_when_missing(self):
        resources = FakeResources([{"id": "other", "url": "/local/other-card.js", "res_type": "module"}], loaded=False)
        hass = hass_with(resources)
        self.assertTrue(await self.register(hass, "0.3.0-beta.13"))
        self.assertEqual(resources.calls[:2], ["load", "items"])
        self.assertEqual(resources.calls.count("create"), 1)
        self.assertTrue(await self.register(hass, "0.3.0-beta.13"))
        self.assertEqual(resources.calls.count("create"), 1)
        self.assertEqual(resources.items[0]["url"], "/local/other-card.js")

    async def test_updates_own_resource_without_affecting_other_cards(self):
        resources = FakeResources(
            [
                {"id": "own", "url": RESOURCE_PATH + "?v=0.3.0-beta.12", "res_type": "module"},
                {"id": "other", "url": "/local/another-card.js?v=1", "res_type": "module"},
            ]
        )
        self.assertTrue(await self.register(hass_with(resources), "0.3.0-beta.13"))
        self.assertEqual(resources.calls.count("update"), 1)
        self.assertEqual(resources.items[0]["url"], RESOURCE_PATH + "?v=0.3.0-beta.13")
        self.assertEqual(resources.items[1]["url"], "/local/another-card.js?v=1")

    async def test_skips_yaml_resource_mode(self):
        resources = FakeResources()
        self.assertFalse(await self.register(hass_with(resources, "yaml"), "0.3.0-beta.13"))
        self.assertEqual(resources.calls, [])

    async def test_skips_ambiguous_duplicates(self):
        resources = FakeResources([
            {"id": "first", "url": RESOURCE_PATH + "?v=0.3.0-beta.11", "res_type": "module"},
            {"id": "second", "url": RESOURCE_PATH + "?v=0.3.0-beta.12", "res_type": "module"},
        ])
        self.assertFalse(await self.register(hass_with(resources), "0.3.0-beta.13"))
        self.assertEqual(resources.calls.count("create"), 0)
        self.assertEqual(resources.calls.count("update"), 0)


if __name__ == "__main__":
    unittest.main()
