"""Alarm lamps from the zone page."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import JvaCoordinator
from .entity import JvaEntity
from .library import load_library

load_library()

from jva_fence.parser import ALARM_NAMES  # noqa: E402

_ALARM_CLASS = {
    "Fence Alarm": BinarySensorDeviceClass.SAFETY,
    "AC Failed": BinarySensorDeviceClass.PROBLEM,
    "Low Battery": BinarySensorDeviceClass.BATTERY,
    "Tamper": BinarySensorDeviceClass.TAMPER,
    "Fault": BinarySensorDeviceClass.PROBLEM,
    "Gate": BinarySensorDeviceClass.PROBLEM,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JvaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for zone in coordinator.data.page.zones:
        if not zone.mode_values:
            continue
        entities.append(JvaVoltageFaultSensor(coordinator, zone.zone_id, zone.name))
        for alarm_name in ALARM_NAMES:
            entities.append(JvaAlarmSensor(coordinator, zone.zone_id, zone.name, alarm_name))
    async_add_entities(entities)


class JvaVoltageFaultSensor(JvaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: JvaCoordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, f"zone-{zone_id}-voltage-fault", f"{zone_name} voltage fault")
        self._zone_id = zone_id

    @property
    def is_on(self) -> bool | None:
        zone = self._zone(self._zone_id)
        if zone is None or zone.voltage_state == "unknown":
            return None
        return zone.voltage_state == "error"


class JvaAlarmSensor(JvaEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: JvaCoordinator,
        zone_id: str,
        zone_name: str,
        alarm_name: str,
    ) -> None:
        slug = alarm_name.lower().replace(" ", "-")
        super().__init__(coordinator, f"zone-{zone_id}-{slug}", f"{zone_name} {alarm_name}")
        self._zone_id = zone_id
        self._alarm_name = alarm_name
        self._attr_device_class = _ALARM_CLASS.get(alarm_name, BinarySensorDeviceClass.PROBLEM)

    @property
    def is_on(self) -> bool | None:
        zone = self._zone(self._zone_id)
        if zone is None:
            return None
        for alarm in zone.alarms:
            if alarm.name == self._alarm_name:
                return alarm.active
        return None
