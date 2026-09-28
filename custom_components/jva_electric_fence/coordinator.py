"""Polling coordinator for the JVA web controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .library import load_library
from .log import LOGGER

load_library()

from jva_fence.client import AuthError, ControllerError, JvaClient  # noqa: E402
from jva_fence.models import PageParse, SetupInfo, ZoneStatus  # noqa: E402


@dataclass
class JvaSnapshot:
    page: PageParse
    setup: SetupInfo


def describe_snapshot(snapshot: JvaSnapshot) -> str:
    setup = snapshot.setup
    parts = [
        f"site={setup.site_name or '-'}",
        f"firmware={setup.firmware or '-'}",
        f"mac={setup.mac or '-'}",
        f"ip={setup.ip or '-'}",
    ]
    zones = [zone for zone in snapshot.page.zones if zone.mode_values] or snapshot.page.zones
    for zone in zones:
        active = [alarm.name for alarm in zone.alarms if alarm.active]
        alarms = ",".join(active) if active else "clear"
        parts.append(
            f"zone={zone.zone_id} mode={zone.mode} return={_reading(zone)} "
            f"state={zone.voltage_state} alarms={alarms}"
        )
    return " ".join(parts)


def _reading(zone: ZoneStatus) -> str:
    if zone.return_voltage_kv is None:
        return zone.reading or "none"
    return f"{zone.return_voltage_kv:.1f}kV"


def scan_interval_seconds(entry: ConfigEntry) -> int:
    raw = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SCAN_INTERVAL
    return max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, value))


class JvaCoordinator(DataUpdateCoordinator[JvaSnapshot]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self._lock = asyncio.Lock()
        self._reauth_started = False
        self._ready_logged = False
        # httpx loads the CA bundle in Client(). That blocks the event loop,
        # so the client is created on the first executor job instead.
        self._client: JvaClient | None = None
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds(entry)),
            config_entry=entry,
        )

    async def _async_update_data(self) -> JvaSnapshot:
        async with self._lock:
            try:
                snapshot = await self.hass.async_add_executor_job(self._pull)
            except AuthError as err:
                LOGGER.warning("AUTH host=%s login rejected", self.host)
                self._start_reauth()
                raise UpdateFailed(f"AUTH host={self.host} login rejected") from err
            except ControllerError as err:
                LOGGER.warning("POLL host=%s failed: %s", self.host, err)
                raise UpdateFailed(f"POLL host={self.host} {err}") from err
            self._log_snapshot(snapshot)
            return snapshot

    def _client_or_create(self) -> JvaClient:
        if self._client is None:
            self._client = JvaClient(
                self.host,
                self.entry.data[CONF_USERNAME],
                self.entry.data[CONF_PASSWORD],
            )
        return self._client

    def _pull(self) -> JvaSnapshot:
        client = self._client_or_create()
        page = client.fetch_page()
        previous = self.data.setup if self.data is not None else None
        try:
            setup = client.fetch_setup()
        except (AuthError, ControllerError):
            if previous is None:
                raise
            LOGGER.warning(
                "SETUP host=%s page unread; keeping the last firmware and network values",
                self.host,
            )
            setup = previous
        return JvaSnapshot(page=page, setup=setup)

    async def async_set_zone_mode(self, zone_id: str, mode: str) -> None:
        LOGGER.info("SET zone=%s mode=%s", zone_id, mode)
        try:
            async with self._lock:
                page = await self.hass.async_add_executor_job(self._set_zone_mode, zone_id, mode)
        except AuthError:
            LOGGER.warning("AUTH host=%s login rejected", self.host)
            self._start_reauth()
            raise
        except ControllerError as err:
            LOGGER.warning("SET zone=%s mode=%s failed: %s", zone_id, mode, err)
            raise
        setup = self.data.setup if self.data is not None else SetupInfo()
        snapshot = JvaSnapshot(page=page, setup=setup)
        zone = page.zone(zone_id)
        if zone is None:
            LOGGER.info("SET zone=%s mode=%s result=missing", zone_id, mode)
        else:
            LOGGER.info(
                "SET zone=%s mode=%s result=%s return=%s state=%s",
                zone_id,
                mode,
                zone.mode,
                _reading(zone),
                zone.voltage_state,
            )
        self.async_set_updated_data(snapshot)

    def _set_zone_mode(self, zone_id: str, mode: str):
        return self._client_or_create().set_zone_mode(zone_id, mode)

    def _start_reauth(self) -> None:
        if self._reauth_started:
            return
        self._reauth_started = True
        self.entry.async_start_reauth(self.hass)

    def _log_snapshot(self, snapshot: JvaSnapshot) -> None:
        detail = describe_snapshot(snapshot)
        if self._ready_logged:
            LOGGER.debug("POLL %s", detail)
            return
        self._ready_logged = True
        LOGGER.info("READY %s", detail)

    async def async_shutdown(self) -> None:
        LOGGER.info("STOP host=%s", self.host)
        await super().async_shutdown()
        client = self._client
        if client is not None:
            await self.hass.async_add_executor_job(client.close)
