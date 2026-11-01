"""Native HA diagnostic sensors for controller-wide demand and alerts."""
from __future__ import annotations
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import callback
from .const import DOMAIN

DESCRIPTIONS=(
    SensorEntityDescription(key='rooms_heating',name='Heating Center Räume mit Heizbedarf',native_unit_of_measurement='Räume',icon='mdi:radiator'),
    SensorEntityDescription(key='warnings',name='Heating Center Warnungen',native_unit_of_measurement='Hinweise',icon='mdi:alert-circle-outline'),
)

async def async_setup_entry(hass, entry, async_add_entities):
    manager=hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatingHealthSensor(manager,entry,description) for description in DESCRIPTIONS])

class HeatingHealthSensor(SensorEntity):
    _attr_should_poll=False
    _attr_has_entity_name=True
    def __init__(self,manager,entry,description):
        self.manager=manager
        self.entity_description=description
        self._attr_unique_id=f'{entry.entry_id}_{description.key}'
        self._attr_name=description.name

    async def async_added_to_hass(self):
        self.async_on_remove(async_track_time_interval(self.hass,self._on_tick,timedelta(seconds=60)))

    @callback
    def _on_tick(self,now):
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self.entity_description.key=='rooms_heating':
            return self.manager.snapshot()['demand_rooms']
        return sum(len(v) for rid,v in self.manager.snapshot()['warnings'].items()
                   if self.manager.rooms.get(rid,{}).get('enabled'))
