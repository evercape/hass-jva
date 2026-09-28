"""Shared device info for JVA entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import JvaCoordinator, JvaSnapshot
from .library import load_library

load_library()

from jva_fence.models import ZoneStatus  # noqa: E402


class JvaEntity(CoordinatorEntity[JvaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: JvaCoordinator, unique_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        ident = _device_id(coordinator)
        self._attr_unique_id = f"{ident}-{unique_suffix}"
        self._attr_name = name

    @property
    def device_info(self) -> DeviceInfo:
        setup = self.coordinator.data.setup
        return DeviceInfo(
            identifiers={(DOMAIN, _device_id(self.coordinator))},
            name=setup.site_name or "JVA Electric Fence",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=setup.firmware,
            configuration_url=self.coordinator.host,
        )

    def _zone(self, zone_id: str) -> ZoneStatus | None:
        data: JvaSnapshot | None = self.coordinator.data
        if data is None:
            return None
        return data.page.zone(zone_id)


def _device_id(coordinator: JvaCoordinator) -> str:
    setup = coordinator.data.setup if coordinator.data is not None else None
    if setup is not None and setup.mac:
        return setup.mac
    return coordinator.entry.entry_id
