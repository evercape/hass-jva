"""Voltage and read-only setup sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import JvaCoordinator
from .entity import JvaEntity

_DIAGNOSTICS = (
    ("firmware", "Firmware", "firmware"),
    ("mac", "MAC address", "mac"),
    ("ip", "IP address", "ip"),
    ("dhcp", "DHCP", "dhcp"),
    ("subnet", "Subnet mask", "subnet"),
    ("gateway", "Default gateway", "gateway"),
    ("dns", "Primary DNS", "dns"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JvaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        JvaDiagnosticSensor(coordinator, key, name, attr) for key, name, attr in _DIAGNOSTICS
    ]
    entities.extend(
        JvaVoltageSensor(coordinator, zone.zone_id, zone.name)
        for zone in coordinator.data.page.zones
        if zone.mode_values
    )
    async_add_entities(entities)


class JvaVoltageSensor(JvaEntity, SensorEntity):
    _attr_native_unit_of_measurement = "kV"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: JvaCoordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, f"zone-{zone_id}-return-kv", f"{zone_name} return voltage")
        self._zone_id = zone_id

    @property
    def native_value(self) -> float | None:
        zone = self._zone(self._zone_id)
        if zone is None:
            return None
        return zone.return_voltage_kv

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        zone = self._zone(self._zone_id)
        if zone is None:
            return {}
        return {"voltage_state": zone.voltage_state, "reading": zone.reading}


class JvaDiagnosticSensor(JvaEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: JvaCoordinator, key: str, name: str, attr: str) -> None:
        super().__init__(coordinator, key, name)
        self._setup_field = attr

    @property
    def native_value(self) -> str | None:
        setup = self.coordinator.data.setup
        value = getattr(setup, self._setup_field)
        return value if value else None
