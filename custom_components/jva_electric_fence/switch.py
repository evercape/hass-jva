"""Arm and disarm switches for JVA zones."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import JvaCoordinator
from .entity import JvaEntity
from .library import load_library

load_library()

from jva_fence.client import AuthError, ControllerError  # noqa: E402

from .const import DOMAIN  # noqa: E402


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JvaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        JvaZoneSwitch(coordinator, zone.zone_id, zone.name)
        for zone in coordinator.data.page.zones
        if zone.mode_values
    )


class JvaZoneSwitch(JvaEntity, SwitchEntity):
    """On sends Armed. Off sends Disarmed.

    Low power still counts as on, because the energiser is running.
    The mode attribute shows armed, low_power, or disarmed.
    """

    def __init__(self, coordinator: JvaCoordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, f"zone-{zone_id}-power", zone_name)
        self._zone_id = zone_id

    @property
    def icon(self) -> str:
        if self.is_on:
            return "mdi:flash"
        return "mdi:flash-off"

    @property
    def is_on(self) -> bool | None:
        zone = self._zone(self._zone_id)
        if zone is None or zone.mode == "unknown":
            return None
        return zone.mode in {"armed", "low_power"}

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        zone = self._zone(self._zone_id)
        if zone is None:
            return {}
        return {
            "mode": zone.mode,
            "voltage_state": zone.voltage_state,
            "reading": zone.reading,
        }

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_mode("armed")

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_mode("disarmed")

    async def _set_mode(self, mode: str) -> None:
        try:
            await self.coordinator.async_set_zone_mode(self._zone_id, mode)
        except AuthError as err:
            raise HomeAssistantError("JVA login was rejected.") from err
        except ControllerError as err:
            raise HomeAssistantError(str(err)) from err
