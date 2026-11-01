"""Local room controller with persistent authoritative setpoints."""
from __future__ import annotations
import asyncio
import logging
import time
from copy import deepcopy
from datetime import timedelta
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from .const import (
    DOMAIN, STORAGE_VERSION, DEFAULT_TARGET, DEFAULT_SCHEDULE,
    RETRY_SECONDS, RECONCILE_SECONDS, SYNC_SECONDS, STALE_SENSOR_SECONDS,
    STALE_DEVICE_SECONDS, TEMP_TOLERANCE,
)
from .policy import valid_temp, room_target, needs_restore, is_locked, next_schedule_change

_LOGGER = logging.getLogger(__name__)


class HeatingManager:
    """Event-driven controller: HA is authority, device input cannot modify it."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, STORAGE_VERSION, DOMAIN)
        self.rooms: dict[str, dict] = {}
        self.mode = "home"
        self._unsubs: list = []
        self._last_sent: dict[str, float] = {}
        self._last_remote_sync: dict[str, float] = {}
        self._last_external_value: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._warnings: dict[str, list[str]] = {}
        self._pending: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._watched: set[str] = set()
        self._active = True

    async def async_start(self) -> None:
        saved = await self.store.async_load() or {}
        self.rooms = saved.get("rooms", {})
        self.mode = saved.get("mode", "home")
        self._update_watch()
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_event))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._on_tick, timedelta(seconds=RECONCILE_SECONDS)
        ))
        # Initial observation only; writes are delayed until the next tick.
        self._compute_warnings()

    async def async_stop(self) -> None:
        self._active = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def _save(self) -> None:
        self.store.async_delay_save(
            lambda: {"rooms": deepcopy(self.rooms), "mode": self.mode}, 2
        )

    def _update_watch(self) -> None:
        self._watched = set()
        for room in self.rooms.values():
            for key in ("sensor", "window", "battery", "availability", "last_seen"):
                if room.get(key):
                    self._watched.add(room[key])
            for key in ("climates", "locks", "external_inputs", "remote_modes"):
                values = room.get(key, {})
                if isinstance(values, dict):
                    self._watched.update(e for e in values.values() if e)
                elif isinstance(values, list):
                    self._watched.update(e for e in values if e)

    @callback
    def _on_event(self, event) -> None:
        entity = event.data.get("entity_id")
        if not self._active or entity not in self._watched:
            return
        for room_id, room in self.rooms.items():
            entities = {room.get(k) for k in ("sensor", "window", "battery", "availability", "last_seen")}
            entities.update(room.get("climates", []))
            for key in ("locks", "external_inputs", "remote_modes"):
                entities.update(room.get(key, {}).values())
            if entity in entities and room.get("enabled"):
                if entity in room.get("climates", []) and not room.get("child_protection"):
                    self._capture_manual_change(room, entity, event)
                self._queue(room_id)

    @callback
    def _capture_manual_change(self, room: dict, climate: str, event) -> None:
        """Unprotected physical changes become legitimate until next schedule event."""
        if self.mode != "home" or self._window(room):
            return
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if not old or not new:
            return
        actual = valid_temp(new.attributes.get("temperature"))
        previous = valid_temp(old.attributes.get("temperature"))
        if actual is None or previous is None or abs(actual - previous) < 0.2:
            return
        if not needs_restore(actual, self._target(room)):
            return
        # Ignore late echo of our own authorized command. Reconcile will handle it.
        if time.monotonic() - self._last_sent.get("temp:" + climate, -1e9) < 120:
            return
        value = round(actual * 2) / 2
        if room.get("schedule_enabled"):
            change = next_schedule_change(room.get("schedule", {}), dt_util.now())
            if change is None:
                return
            room["override_temp"] = value
            room["override_until"] = change.isoformat()
        else:
            room["target"] = value
            room["override_temp"] = None
            room["override_until"] = None
        self._save()

    @callback
    def _on_tick(self, now) -> None:
        if not self._active:
            return
        for room_id, room in self.rooms.items():
            if room.get("enabled"):
                self._queue(room_id)
        self._compute_warnings()

    def _queue(self, room_id: str) -> None:
        if room_id in self._pending:
            return
        self._pending.add(room_id)
        self.hass.async_create_task(self._reconcile(room_id))

    def _state(self, entity: str | None):
        return self.hass.states.get(entity) if entity else None

    def _valid_sensor(self, room: dict) -> float | None:
        state = self._state(room.get("sensor"))
        if not state:
            return None
        value = valid_temp(state.state, -20, 60)
        if value is None:
            return None
        last_report = getattr(state, "last_reported", state.last_updated)
        age = (dt_util.utcnow() - last_report).total_seconds()
        if age > int(room.get("sensor_max_age", STALE_SENSOR_SECONDS)):
            return None
        return value

    def _window(self, room: dict) -> bool:
        state = self._state(room.get("window"))
        return bool(state and state.state == "on")

    def _target(self, room: dict) -> float:
        tmp = dict(room, window_open=self._window(room))
        return room_target(tmp, self.mode, dt_util.now())

    async def _call(self, domain: str, service: str, data: dict, key: str) -> bool:
        now = time.monotonic()
        if now - self._last_sent.get(key, -1e9) < RETRY_SECONDS:
            return False
        self._last_sent[key] = now
        try:
            if not self.hass.services.has_service(domain,service):
                raise ValueError(f'Service {domain}.{service} ist nicht verfügbar')
            await self.hass.services.async_call(domain, service, data, blocking=True)
            return True
        except Exception:
            self._failures[key] = self._failures.get(key, 0) + 1
            _LOGGER.exception("Heating Center command failed: %s", key)
            return False

    async def _lock_device(self, entity: str) -> None:
        state = self._state(entity)
        if state is None or state.state in ("unavailable", "unknown") or is_locked(state.state):
            return
        domain = entity.split(".")[0]
        if domain == "switch":
            await self._call("switch", "turn_on", {"entity_id": entity}, "lock:" + entity)
        elif domain == "select":
            options = state.attributes.get("options", [])
            option = next((v for v in ("LOCK", "lock", "Locked", "locked", "ON") if v in options), None)
            if option:
                await self._call("select", "select_option", {"entity_id": entity, "option": option}, "lock:" + entity)
        elif domain == "lock":
            await self._call("lock", "lock", {"entity_id": entity}, "lock:" + entity)

    async def _external(self, room: dict, climate: str, value: float | None) -> None:
        number_entity = room.get("external_inputs", {}).get(climate)
        mode_entity = room.get("remote_modes", {}).get(climate)
        if value is None:
            # Sensor missing: ask the TRV to use its internal sensor.
            if mode_entity:
                await self._sensor_mode(mode_entity, False)
            return
        # The Sonoff input supports 0..99.9 C. Never write out-of-range
        # measurements, and do not select remote mode unless a recent value
        # has actually been sent successfully.
        if value < 0 or value > 99.9:
            if mode_entity:
                await self._sensor_mode(mode_entity, False)
            return
        if number_entity:
            key = "external:" + number_entity
            previous = self._last_external_value.get(key)
            changed = previous is None or abs(previous - value) >= 0.2
            if changed or time.monotonic() - self._last_remote_sync.get(key, -1e9) >= SYNC_SECONDS:
                ok = await self._call(
                    "number", "set_value", {"entity_id": number_entity, "value": round(value, 1)}, key
                )
                if ok:
                    self._last_remote_sync[key] = time.monotonic()
                    self._last_external_value[key] = value
                elif time.monotonic() - self._last_remote_sync.get(key, -1e9) > SYNC_SECONDS * 2:
                    if mode_entity:
                        await self._sensor_mode(mode_entity, False)
                    return
        # Never select an external sensor which we have not written successfully.
        if mode_entity and number_entity and self._last_remote_sync.get("external:" + number_entity):
            await self._sensor_mode(mode_entity, True)

    async def _sensor_mode(self, entity: str, remote: bool) -> None:
        state = self._state(entity)
        if not state or state.state in ("unavailable", "unknown"):
            return
        options = state.attributes.get("options", [])
        options_to_try = ("remote_temperature", "external") if remote else ("local_temperature",)
        desired = next((v for v in options_to_try if v in options), None)
        if desired and state.state != desired:
            await self._call("select", "select_option", {"entity_id": entity, "option": desired}, "mode:" + entity)

    async def _reconcile(self, room_id: str) -> None:
        lock = self._locks.setdefault(room_id, asyncio.Lock())
        try:
            async with lock:
                room = self.rooms.get(room_id)
                if not self._active or not room or not room.get("enabled"):
                    return
                target = self._target(room)
                external = self._valid_sensor(room) if room.get("sensor") else None
                for entity in room.get("climates", []):
                    state = self._state(entity)
                    if not state or state.state in ("unavailable", "unknown"):
                        continue
                    current = state.attributes.get("temperature")
                    if needs_restore(current, target, TEMP_TOLERANCE):
                        await self._call(
                            "climate", "set_temperature",
                            {"entity_id": entity, "temperature": target}, "temp:" + entity
                        )
                    if room.get("child_protection"):
                        lock_entity = room.get("locks", {}).get(entity)
                        if lock_entity:
                            await self._lock_device(lock_entity)
                    if room.get("sensor"):
                        await self._external(room, entity, external)
                self._compute_warnings()
        finally:
            self._pending.discard(room_id)

    def _compute_warnings(self) -> None:
        result = {}
        for room_id, room in self.rooms.items():
            if not room.get("enabled"):
                result[room_id] = ["Raumsteuerung noch nicht aktiviert"]
                continue
            warnings = []
            target = self._target(room)
            sensor = room.get("sensor")
            if sensor and self._valid_sensor(room) is None:
                warnings.append("Externer Temperatursensor fehlt, ist ungültig oder meldet zu lange nicht")
            battery = self._state(room.get("battery"))
            if battery and battery.state not in ("unknown", "unavailable"):
                try:
                    if float(battery.state) <= int(room.get("battery_warning", 20)):
                        warnings.append("Batterie schwach: " + battery.state + " %")
                except ValueError:
                    pass
            availability = self._state(room.get("availability"))
            if availability and availability.state in ("off", "unavailable", "unknown"):
                warnings.append("Zigbee-Verfügbarkeit meldet offline")
            seen = self._state(room.get("last_seen"))
            if seen and seen.state not in ("unknown", "unavailable"):
                try:
                    last = dt_util.parse_datetime(seen.state)
                    if last and (dt_util.utcnow() - dt_util.as_utc(last)).total_seconds() > STALE_DEVICE_SECONDS:
                        warnings.append("Letzter Zigbee-Kontakt zu lange her")
                except (TypeError, ValueError):
                    pass
            for entity in room.get("climates", []):
                state = self._state(entity)
                if not state or state.state in ("unavailable", "unknown"):
                    warnings.append(entity + ": nicht verfügbar")
                    continue
                if needs_restore(state.attributes.get("temperature"), target):
                    warnings.append(entity + ": Sollwert weicht ab (Wiederherstellung läuft)")
                if self._failures.get("temp:" + entity, 0) >= 3:
                    warnings.append(entity + ": wiederholte Schreibfehler")
                if room.get("child_protection"):
                    lock_entity = room.get("locks", {}).get(entity)
                    lock = self._state(lock_entity)
                    if not lock_entity:
                        warnings.append(entity + ": keine physische Kindersperr-Entität zugeordnet")
                    elif not lock or lock.state in ("unavailable", "unknown"):
                        warnings.append(entity + ": Sperrstatus nicht verfügbar")
                    elif not is_locked(lock.state):
                        warnings.append(entity + ": Kindersperre ausgeschaltet; wird reaktiviert")
                if sensor and not room.get("external_inputs", {}).get(entity):
                    warnings.append(entity + ": externe Temperatur-Zielentität fehlt")
            result[room_id] = warnings
        self._warnings = result

    def snapshot(self):
        self._compute_warnings()
        return {
            "entry_id": self.entry.entry_id,
            "mode": self.mode,
            "rooms": deepcopy(self.rooms),
            "warnings": self._warnings,
            "calculated_targets": {rid: self._target(room) for rid, room in self.rooms.items()},
            "version": "0.1.0-beta.1",
        }

    async def add_room(self, data: dict) -> None:
        rid = str(data.get("id", "")).strip()
        if not rid or len(rid) > 60 or not all(c.isalnum() or c in "_-" for c in rid):
            raise ValueError("Ungültige Raum-ID")
        existing = self.rooms.get(rid, {})
        climates = data.get("climates", existing.get("climates", []))
        if not isinstance(climates, list) or not climates or len(climates) > 12 or any(
            not isinstance(e, str) or not e.startswith("climate.") for e in climates
        ):
            raise ValueError("Bitte mindestens eine climate-Entität auswählen")
        for other_id, other in self.rooms.items():
            if other_id != rid and set(climates) & set(other.get("climates", [])):
                raise ValueError("Ein Thermostat darf nur zu einem Raum gehören")
        target = valid_temp(data.get("target", existing.get("target", DEFAULT_TARGET)))
        if target is None:
            raise ValueError("Ungültige Solltemperatur")
        room = {
            "id": rid,
            "name": str(data.get("name", existing.get("name", rid)))[:90],
            "group": str(data.get("group", existing.get("group", "")))[:90],
            "climates": climates,
            "sensor": str(data.get("sensor", existing.get("sensor", ""))),
            "window": str(data.get("window", existing.get("window", ""))),
            "battery": str(data.get("battery", existing.get("battery", ""))),
            "availability": str(data.get("availability", existing.get("availability", ""))),
            "last_seen": str(data.get("last_seen", existing.get("last_seen", ""))),
            "locks": data.get("locks", existing.get("locks", {})),
            "external_inputs": data.get("external_inputs", existing.get("external_inputs", {})),
            "remote_modes": data.get("remote_modes", existing.get("remote_modes", {})),
            "target": round(target * 2) / 2,
            "away_temp": valid_temp(data.get("away_temp", existing.get("away_temp", 16))) or 16,
            "vacation_temp": valid_temp(data.get("vacation_temp", existing.get("vacation_temp", 12))) or 12,
            "window_temp": valid_temp(data.get("window_temp", existing.get("window_temp", 12))) or 12,
            "child_protection": bool(data.get("child_protection", existing.get("child_protection", False))),
            "enabled": bool(data.get("enabled", existing.get("enabled", False))),
            "schedule_enabled": bool(data.get("schedule_enabled", existing.get("schedule_enabled", False))),
            "schedule": data.get("schedule", existing.get("schedule", deepcopy(DEFAULT_SCHEDULE))),
            "override_temp": existing.get("override_temp"),
            "override_until": existing.get("override_until"),
            "sensor_max_age": int(data.get("sensor_max_age", existing.get("sensor_max_age", STALE_SENSOR_SECONDS))),
            "battery_warning": int(data.get("battery_warning", existing.get("battery_warning", 20))),
        }
        for key in ("locks", "external_inputs", "remote_modes"):
            if not isinstance(room[key], dict):
                raise ValueError("Fehlerhafte Zuordnung: " + key)
            room[key] = {k: v for k, v in room[key].items() if k in climates and isinstance(v, str)}
        if not isinstance(room["schedule"], dict):
            raise ValueError("Ungültiger Wochenplan")
        if not isinstance(room['schedule'], dict):
            raise ValueError('Ungültiger Wochenplan')
        self.rooms[rid] = room
        self._save()
        self._update_watch()
        self._queue(rid)

    async def remove_room(self, rid: str) -> None:
        self.rooms.pop(rid, None)
        self._save()
        self._update_watch()

    async def set_room_temperature(self, rid: str, value, minutes=None) -> None:
        room = self.rooms.get(rid)
        if room is None:
            raise ValueError("Raum nicht gefunden")
        value = valid_temp(value)
        if value is None:
            raise ValueError("Ungültige Temperatur")
        value = round(value * 2) / 2
        if minutes is None:
            minutes = 120 if room.get("schedule_enabled") else 0
        minutes = int(minutes)
        if not 0 <= minutes <= 1440:
            raise ValueError("Dauer muss 0 bis 1440 Minuten betragen")
        if minutes:
            room["override_temp"] = value
            room["override_until"] = (dt_util.now() + timedelta(minutes=minutes)).isoformat()
        else:
            room["target"] = value
            room["override_temp"] = None
            room["override_until"] = None
        self._save()
        self._queue(rid)

    async def set_group_temperature(self, group: str, value, minutes=None) -> None:
        members = [rid for rid, r in self.rooms.items() if r.get("group") == group and group]
        if not members:
            raise ValueError("Gruppe nicht gefunden")
        for rid in members:
            await self.set_room_temperature(rid, value, minutes)

    async def set_mode(self, mode: str) -> None:
        if mode not in ("home", "away", "vacation"):
            raise ValueError("Ungültiger Modus")
        self.mode = mode
        self._save()
        for rid in self.rooms:
            self._queue(rid)