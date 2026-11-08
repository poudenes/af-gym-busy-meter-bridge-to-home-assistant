"""Sensoren: drukte nu, gebruikelijke drukte en advies per club."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERDICTS
from .coordinator import AFConfigEntry, AFCoordinator, Club

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AFSensorDescription(SensorEntityDescription):
    """Beschrijving van een AF-sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[Club, dict[str, Any]], dict[str, Any]] | None = None
    suffix: str  # achtervoegsel van de entity_id, gelijk aan de oude bridge


SENSORS: tuple[AFSensorDescription, ...] = (
    AFSensorDescription(
        key="current",
        translation_key="current",
        suffix="",
        native_unit_of_measurement="personen",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["current"],
        attrs_fn=lambda club, d: {
            "club": club.name,
            "af_number": club.af_number,
            "typical_count": d["typical"],
            "ratio": d["ratio"],
            "verdict": d["verdict"],
            "verdict_message": d["verdict_message"],
            "rest_of_day": d["rest_of_day"],
            "updated": d["updated"],
        },
    ),
    AFSensorDescription(
        key="typical",
        translation_key="typical",
        suffix="_normaal",
        native_unit_of_measurement="personen",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d["typical"],
    ),
    AFSensorDescription(
        key="verdict",
        translation_key="verdict",
        suffix="_advies",
        device_class=SensorDeviceClass.ENUM,
        options=VERDICTS,
        value_fn=lambda d: d["verdict"],
        attrs_fn=lambda club, d: {"message": d["verdict_message"]},
    ),
)


def base_object_id(club: Club) -> str:
    """sensor.af_drukte voor de thuisclub, sensor.af_drukte_nl_1001 voor extra clubs."""
    if club.is_home:
        return "af_drukte"
    return "af_drukte_" + re.sub(r"[^a-z0-9]+", "_", club.af_number.lower()).strip("_")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AFConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Maak sensoren aan voor elke gevolgde club."""
    coordinator = entry.runtime_data
    async_add_entities(
        AFSensor(coordinator, club, description)
        for club in coordinator.clubs
        for description in SENSORS
    )


class AFSensor(CoordinatorEntity[AFCoordinator], SensorEntity):
    """Eén sensor voor één club."""

    entity_description: AFSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: AFCoordinator, club: Club, description: AFSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._club = club
        self._attr_unique_id = f"{club.af_number}_{description.key}"
        # Zelfde entity_id als de oude Docker-bridge, zodat dashboards blijven werken.
        self.entity_id = f"sensor.{base_object_id(club)}{description.suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, club.af_number)},
            name=f"Anytime Fitness {club.name}",
            manufacturer="Anytime Fitness",
            model=club.af_number,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _data(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._club.af_number)

    @property
    def available(self) -> bool:
        return super().available and self._data is not None

    @property
    def native_value(self) -> Any:
        data = self._data
        return None if data is None else self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._data
        if data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self._club, data)
