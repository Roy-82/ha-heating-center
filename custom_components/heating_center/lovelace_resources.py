"""Idempotent Lovelace resource registration for the Heating Center card.

Never edit the resource collection before it is fully loaded from HA storage.
This matters on HA versions where Lovelace resources load lazily on startup.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

CARD_RESOURCE_PATH = "/heating_center_assets/heating-center-card.js"


async def async_register_card_resource(hass: HomeAssistant, version: str) -> bool:
    """Ensure exactly one versioned resource exists in Lovelace storage mode.

    Only the Heating Center resource is created/updated. Other resources are
    untouched; conflicting duplicate registrations are logged, not deleted.
    """
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        _LOGGER.warning(
            "Lovelace ist noch nicht geladen; Heating-Center-Kartenressource "
            "konnte nicht automatisch registriert werden"
        )
        return False

    if getattr(lovelace, "resource_mode", None) != "storage":
        _LOGGER.info(
            "Lovelace verwendet YAML-Ressourcen; Heating-Center-Karte muss "
            "in lovelace.resources manuell eingetragen werden"
        )
        return False

    resources = lovelace.resources

    # CRITICAL: calling async_items/create before the Lovelace collection
    # has loaded can overwrite other resources on affected HA versions.
    if not resources.loaded:
        await resources.async_load()

    expected_url = f"{CARD_RESOURCE_PATH}?v={version}"
    matches = [
        item for item in resources.async_items()
        if str(item.get("url", "")).split("?", 1)[0] == CARD_RESOURCE_PATH
    ]

    if len(matches) > 1:
        _LOGGER.warning(
            "Es sind %s Heating-Center-Kartenressourcen vorhanden. "
            "Automatische Änderung zum Schutz der vorhandenen Einträge "
            "übersprungen. Bitte Dubletten unter Dashboard-Ressourcen prüfen.",
            len(matches),
        )
        return False

    if matches:
        current = matches[0]
        if (
            current.get("url") == expected_url
            and current.get("res_type") == "module"
        ):
            _LOGGER.debug("Heating-Center-Kartenressource bereits aktuell: %s", expected_url)
            return True
        await resources.async_update_item(
            current["id"], {"url": expected_url, "res_type": "module"}
        )
        _LOGGER.info("Heating-Center-Kartenressource aktualisiert: %s", expected_url)
        return True

    await resources.async_create_item({"url": expected_url, "res_type": "module"})
    _LOGGER.info("Heating-Center-Kartenressource automatisch angelegt: %s", expected_url)
    return True
