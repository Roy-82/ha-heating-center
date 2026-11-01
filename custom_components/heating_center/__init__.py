"""HA Heating Center: HACS custom integration and administration panel."""
from __future__ import annotations
from pathlib import Path
import logging
import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN
from .advanced import AdvancedHeatingManager as HeatingManager

_LOGGER = logging.getLogger(__name__)

PANEL_VERSION = "0.3.0-beta.6"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _get_manager(hass: HomeAssistant, entry_id: str) -> HeatingManager:
    manager = hass.data.get(DOMAIN, {}).get(entry_id)
    if manager is None:
        raise ValueError("Heating Center Instanz wurde nicht gefunden")
    return manager


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "heating_center/get"})
@websocket_api.async_response
async def ws_get(hass, connection, msg):
    managers = hass.data.get(DOMAIN, {})
    if not managers:
        connection.send_error(msg["id"], "not_ready", "Heating Center noch nicht geladen")
        return
    manager = next(iter(managers.values()))
    try:
        snapshot = manager.snapshot()
    except Exception:
        _LOGGER.exception("Failed to build Heating Center dashboard snapshot")
        connection.send_error(
            msg["id"], "snapshot_failed",
            "Heating-Center-Daten konnten nicht geladen werden; bitte HA-Protokoll pruefen",
        )
        return
    snapshot["panel_backend_version"] = PANEL_VERSION
    snapshot["session_admin"] = bool(connection.user and connection.user.is_admin)
    connection.send_result(msg["id"], snapshot)


# Panel writes use the same authenticated WebSocket session as dashboard reads.
# Keep the original Home Assistant services available to existing automations.
_WS_ACTION_SCHEMAS = {
    "add_room": vol.Schema({vol.Required("room"): dict}),
    "remove_room": vol.Schema({vol.Required("room_id"): cv.string}),
    "set_room_temperature": vol.Schema({
        vol.Required("room_id"): cv.string,
        vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=4, max=35)),
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    }),
    "set_group_temperature": vol.Schema({
        vol.Required("group"): cv.string,
        vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=4, max=35)),
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    }),
    "set_mode": vol.Schema({vol.Required("mode"): vol.In(["home", "away", "vacation"])}),
    "set_settings": vol.Schema({vol.Required("settings"): dict}),
    "apply_profile": vol.Schema({
        vol.Required("room_id"): cv.string,
        vol.Required("profile"): vol.In(["comfort", "eco", "night", "boost"]),
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    }),
    "export_schedule": vol.Schema({vol.Required("room_id"): cv.string}),
}


async def _execute_panel_action(manager: HeatingManager, action: str, data: dict) -> None:
    """Execute only allow-listed Heating Center actions with validated arguments."""
    values = _WS_ACTION_SCHEMAS[action](data)
    if action == "add_room":
        await manager.add_room(values["room"])
    elif action == "remove_room":
        await manager.remove_room(values["room_id"])
    elif action == "set_room_temperature":
        await manager.set_room_temperature(
            values["room_id"], values["temperature"], values.get("minutes")
        )
    elif action == "set_group_temperature":
        await manager.set_group_temperature(
            values["group"], values["temperature"], values.get("minutes")
        )
    elif action == "set_mode":
        await manager.set_mode(values["mode"])
    elif action == "set_settings":
        await manager.set_settings(values["settings"])
    elif action == "apply_profile":
        await manager.apply_profile(
            values["room_id"], values["profile"], values.get("minutes", 120)
        )
    elif action == "export_schedule":
        await manager.sync_native_schedule(values["room_id"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "heating_center/execute",
    vol.Required("config_entry_id"): cv.string,
    vol.Required("action"): vol.In(list(_WS_ACTION_SCHEMAS)),
    vol.Required("data"): dict,
})
@websocket_api.async_response
async def ws_execute(hass, connection, msg):
    """Apply dashboard changes for authenticated Home Assistant administrators."""
    _LOGGER.debug("Heating Center WebSocket action requested: %s", msg["action"])
    manager = hass.data.get(DOMAIN, {}).get(msg["config_entry_id"])
    if manager is None:
        connection.send_error(msg["id"], "not_found", "Heating Center ist nicht geladen")
        return
    try:
        await _execute_panel_action(manager, msg["action"], msg["data"])
    except (ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_request", str(err))
        return
    except Exception:
        _LOGGER.exception("Heating Center dashboard action failed: %s", msg["action"])
        connection.send_error(
            msg["id"], "action_failed", "Speichern fehlgeschlagen; Details im HA-Protokoll"
        )
        return
    connection.send_result(msg["id"], {"ok": True})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_execute)

    async def add_room(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).add_room(call.data["room"])

    async def remove_room(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).remove_room(call.data["room_id"])

    async def set_room_temperature(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).set_room_temperature(
            call.data["room_id"], call.data["temperature"], call.data.get("minutes")
        )

    async def set_group_temperature(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).set_group_temperature(
            call.data["group"], call.data["temperature"], call.data.get("minutes")
        )

    async def set_mode(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).set_mode(call.data["mode"])

    async def set_settings(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).set_settings(call.data["settings"])

    async def apply_profile(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).apply_profile(
            call.data["room_id"],call.data["profile"],call.data.get("minutes",120)
        )

    async def export_schedule(call: ServiceCall) -> None:
        await _get_manager(hass, call.data["config_entry_id"]).sync_native_schedule(call.data["room_id"])

    entry = vol.Required("config_entry_id")
    hass.services.async_register(DOMAIN, "add_room", add_room, schema=vol.Schema({
        entry: cv.string, vol.Required("room"): dict
    }))
    hass.services.async_register(DOMAIN, "remove_room", remove_room, schema=vol.Schema({
        entry: cv.string, vol.Required("room_id"): cv.string
    }))
    schema_temp = vol.Schema({
        entry: cv.string, vol.Required("room_id"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    })
    hass.services.async_register(DOMAIN, "set_room_temperature", set_room_temperature, schema=schema_temp)
    hass.services.async_register(DOMAIN, "set_group_temperature", set_group_temperature, schema=vol.Schema({
        entry: cv.string, vol.Required("group"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
    }))
    hass.services.async_register(DOMAIN, "set_mode", set_mode, schema=vol.Schema({
        entry: cv.string, vol.Required("mode"): vol.In(["home", "away", "vacation"])
    }))
    hass.services.async_register(DOMAIN,"set_settings",set_settings,schema=vol.Schema({
        entry:cv.string, vol.Required("settings"):dict,
    }))
    hass.services.async_register(DOMAIN,"apply_profile",apply_profile,schema=vol.Schema({
        entry:cv.string,vol.Required("room_id"):cv.string,
        vol.Required("profile"):vol.In(["comfort","eco","night","boost"]),
        vol.Optional("minutes"):vol.All(vol.Coerce(int),vol.Range(min=0,max=1440)),
    }))
    hass.services.async_register(DOMAIN,"export_schedule",export_schedule,schema=vol.Schema({
        entry:cv.string,vol.Required("room_id"):cv.string,
    }))
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths([
        StaticPathConfig("/heating_center_assets", str(frontend_dir), False)
    ])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = HeatingManager(hass, entry)
    await manager.async_start()
    hass.data[DOMAIN][entry.entry_id] = manager
    await hass.config_entries.async_forward_entry_setups(entry,["sensor"])
    # Register panel only once. Panel access restricted to HA admins.
    if not frontend.async_panel_exists(hass, DOMAIN):
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="heating-center-panel-v6",
            frontend_url_path=DOMAIN,
            sidebar_title="Heating Center",
            sidebar_icon="mdi:radiator",
            module_url=f"/heating_center_assets/heating-center-panel-v6.js?v={PANEL_VERSION}",
            embed_iframe=False,
            require_admin=True,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if manager:
        await manager.async_stop()
    await hass.config_entries.async_unload_platforms(entry,["sensor"])
    if not hass.data.get(DOMAIN):
        frontend.async_remove_panel(hass, DOMAIN, warn_if_unknown=False)
    return True
