"""Logging for the JVA Electric Fence integration.

Every message uses one logger name, custom_components.jva_electric_fence,
the same pattern as Irrigation Unlimited. Enable it with:

logger:
  default: info
  logs:
    custom_components.jva_electric_fence: debug
"""

from __future__ import annotations

import logging

from .const import VERSION

LOGGER = logging.getLogger(__package__)


def startup_message(host: str, interval: int) -> str:
    return (
        "\n-------------------------------------------------------------------\n"
        "JVA Electric Fence\n"
        f"Version: {VERSION}\n"
        f"Host: {host}\n"
        f"Polling: {interval}s\n"
        "-------------------------------------------------------------------"
    )
