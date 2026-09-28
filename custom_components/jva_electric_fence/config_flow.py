"""UI config flow for the JVA controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .library import load_library

load_library()

from jva_fence.client import AuthError, ControllerError, JvaClient, normalize_host  # noqa: E402
from jva_fence.models import SetupInfo  # noqa: E402


class FlowError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _interval_field() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=MAX_SCAN_INTERVAL,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _validate(host: str, username: str, password: str) -> SetupInfo:
    client = JvaClient(host, username, password)
    try:
        page = client.fetch_page()
        setup = client.fetch_setup()
    except AuthError as err:
        raise FlowError("invalid_auth") from err
    except ControllerError as err:
        raise FlowError("cannot_connect") from err
    finally:
        client.close()
    if not any(zone.mode_values for zone in page.zones):
        raise FlowError("no_controls")
    return setup


async def _async_validate(hass: HomeAssistant, host: str, username: str, password: str) -> SetupInfo:
    return await hass.async_add_executor_job(_validate, host, username, password)


class JvaOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(title="", data=user_input)
        current = int(self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCAN_INTERVAL, default=current): _interval_field()}
            ),
        )


class JvaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> JvaOptionsFlow:
        return JvaOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
                setup = await _async_validate(
                    self.hass,
                    host,
                    user_input[CONF_USERNAME].strip(),
                    user_input[CONF_PASSWORD],
                )
            except ControllerError:
                errors["base"] = "cannot_connect"
            except FlowError as err:
                errors["base"] = err.code
            except Exception:
                errors["base"] = "unknown"
            else:
                unique = setup.mac or host
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                interval = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
                return self.async_create_entry(
                    title=setup.site_name or "JVA Electric Fence",
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={CONF_SCAN_INTERVAL: interval},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _interval_field(),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await _async_validate(
                    self.hass,
                    entry.data[CONF_HOST],
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except FlowError as err:
                errors["base"] = err.code
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )
