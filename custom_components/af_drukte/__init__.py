"""Anytime Fitness drukte: live bezetting van AF-clubs in Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AFClient
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN
from .coordinator import AFConfigEntry, AFCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AFConfigEntry) -> bool:
    """Zet de integratie op vanuit een config entry."""

    @callback
    def save_tokens(tokens: dict[str, Any]) -> None:
        """Bewaar ververste tokens zodat een herstart geen nieuwe login vraagt."""
        hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens})

    client = AFClient(
        async_get_clientsession(hass),
        {
            "access_token": entry.data.get(CONF_ACCESS_TOKEN),
            "refresh_token": entry.data.get(CONF_REFRESH_TOKEN),
            "expires_at": entry.data.get(CONF_EXPIRES_AT, 0),
        },
        save_tokens,
    )
    coordinator = AFCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Opties wijzigen herlaadt de entry via OptionsFlowWithReload; geen update
    # listener, want die zou ook bij elk ververst token herladen.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AFConfigEntry) -> bool:
    """Ontlaad een config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
