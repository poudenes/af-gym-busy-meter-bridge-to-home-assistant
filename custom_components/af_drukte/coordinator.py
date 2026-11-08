"""Coordinator die periodiek de drukte van alle gekozen clubs ophaalt."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AFAuthError, AFClient, AFError, summarize
from .const import (
    CONF_CLUB_NAMES,
    CONF_CLUBS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type AFConfigEntry = ConfigEntry[AFCoordinator]


@dataclass
class Club:
    """Een gevolgde club."""

    af_number: str
    name: str
    is_home: bool


class AFCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Haalt per interval de busy-meter op voor de thuisclub en extra clubs."""

    config_entry: AFConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AFConfigEntry, client: AFClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.home: dict[str, Any] | None = None
        self.clubs: list[Club] = []

    async def _async_setup(self) -> None:
        """Eenmalig: thuisclub opvragen en de lijst met clubs opbouwen."""
        try:
            self.home = await self.client.home_gym()
        except AFAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except AFError as exc:
            raise UpdateFailed(f"Thuisclub ophalen mislukt: {exc}") from exc
        home_number = self.home["afNumber"]
        self.clubs = [Club(home_number, self.home.get("name") or home_number, True)]
        names = self.config_entry.options.get(CONF_CLUB_NAMES, {})
        for number in self.config_entry.options.get(CONF_CLUBS, []):
            if number != home_number:
                self.clubs.append(Club(number, names.get(number, number), False))

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        results = await asyncio.gather(
            *(self.client.busy_meter(club.af_number) for club in self.clubs),
            return_exceptions=True,
        )
        moment = dt_util.now()
        data: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for club, result in zip(self.clubs, results, strict=True):
            if isinstance(result, AFAuthError):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, BaseException):
                if not isinstance(result, AFError):
                    raise result
                errors.append(f"{club.name}: {result}")
                continue
            data[club.af_number] = summarize(result, moment)
        if errors:
            if not data:
                raise UpdateFailed("; ".join(errors))
            _LOGGER.warning("Drukte ophalen deels mislukt: %s", "; ".join(errors))
        return data
