"""Parsed controller state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AlarmFlag:
    name: str
    active: bool | None


@dataclass
class ZoneStatus:
    zone_id: str
    name: str
    mode: str
    return_voltage_kv: float | None
    voltage_state: str
    reading: str | None = None
    alarms: list[AlarmFlag] = field(default_factory=list)
    field_name: str | None = None
    mode_values: dict[str, str] = field(default_factory=dict)
    form_method: str | None = None
    form_action: str | None = None
    form_fields: dict[str, str] = field(default_factory=dict)
    mode_onclicks: dict[str, str] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("form_fields", None)
        data.pop("form_action", None)
        data.pop("form_method", None)
        data.pop("field_name", None)
        data.pop("mode_values", None)
        data.pop("mode_onclicks", None)
        data["can_control"] = bool(self.mode_values) and (
            bool(self.field_name and self.form_action) or bool(self.mode_onclicks)
        )
        data["modes"] = sorted(self.mode_values)
        return data


@dataclass
class LinkInfo:
    text: str
    url: str


@dataclass
class SetupInfo:
    """Read-only fields from the setup page.

    Usernames and passwords are not parsed. The setup form is never submitted.
    """

    firmware: str | None = None
    mac: str | None = None
    ip: str | None = None
    dhcp: str | None = None
    subnet: str | None = None
    gateway: str | None = None
    dns: str | None = None
    site_name: str | None = None


@dataclass
class PageParse:
    title: str
    zones: list[ZoneStatus]
    links: list[LinkInfo]
    form_field_names: list[str]
    has_clear_alarms: bool
    clear_alarms_name: str | None = None
    clear_alarms_value: str | None = None
    clear_form_method: str | None = None
    clear_form_action: str | None = None
    clear_form_fields: dict[str, str] = field(default_factory=dict)
    frames: list[str] = field(default_factory=list)

    def zone(self, zone_id: str) -> ZoneStatus | None:
        wanted = zone_id.lower()
        for zone in self.zones:
            if zone.zone_id.lower() == wanted:
                return zone
        return None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "zones": [zone.to_public_dict() for zone in self.zones],
            "links": [asdict(link) for link in self.links],
            "form_field_names": self.form_field_names,
            "has_clear_alarms": self.has_clear_alarms,
            "frames": self.frames,
        }
