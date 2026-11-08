"""Tests voor de config flow, sensoren, tokenverversing en opties."""

from __future__ import annotations

import time

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.af_drukte.api import API_BASE
from custom_components.af_drukte.config_flow import normalize_phone
from custom_components.af_drukte.const import (
    CONF_ACCESS_TOKEN,
    CONF_CLUB_NAMES,
    CONF_CLUBS,
    CONF_EXPIRES_AT,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import HOME, PHONE, FakeAF

ROWS = [("17:00:00", 10), ("18:00:00", 20), ("19:00:00", 8)]


@pytest.fixture(autouse=True)
async def frozen(freezer: FrozenDateTimeFactory, hass: HomeAssistant) -> None:
    # 17:30 lokale tijd -> uur 17 telt (gebruikelijk 10).
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-11-09 17:30:00+01:00")


def test_normalize_phone() -> None:
    assert normalize_phone("06 1234 5678") == "+31612345678"
    assert normalize_phone("0031612345678") == "+31612345678"
    assert normalize_phone("+32 470 12 34 56") == "+32470123456"
    assert normalize_phone("abc") is None


async def test_config_flow(hass: HomeAssistant, fake_af: FakeAF) -> None:
    fake_af.gym()
    fake_af.meter(HOME, 4, ROWS)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "abc"}
    )
    assert result["errors"] == {"phone": "invalid_phone"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"phone": "06-12345678"}
    )
    assert result["step_id"] == "code"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "999"})
    assert result["errors"] == {"base": "invalid_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anytime Fitness Thuisclub"
    assert result["result"].unique_id == PHONE
    assert result["data"]["refresh_token"] == "ref-1"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.af_drukte").state == "4"


async def test_sensors(hass: HomeAssistant, fake_af: FakeAF, entry: MockConfigEntry) -> None:
    fake_af.gym()
    fake_af.meter(HOME, 4, ROWS)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get("sensor.af_drukte")
    assert state.state == "4"
    assert state.attributes["club"] == "Thuisclub"
    assert state.attributes["typical_count"] == 10
    assert state.attributes["ratio"] == 0.4
    assert state.attributes["verdict"] == "go-now"
    assert state.attributes["rest_of_day"] == [
        {"hour": "17:00", "typicalCount": 10},
        {"hour": "18:00", "typicalCount": 20},
        {"hour": "19:00", "typicalCount": 8},
    ]
    assert state.attributes["updated"].startswith("2026-11-09T17:30")
    assert state.attributes["unit_of_measurement"] == "personen"
    assert hass.states.get("sensor.af_drukte_normaal").state == "10"
    advies = hass.states.get("sensor.af_drukte_advies")
    assert advies.state == "go-now"
    assert advies.attributes["message"].startswith("Veel rustiger")

    registry = er.async_get(hass)
    assert registry.async_get("sensor.af_drukte").unique_id == f"{HOME}_current"


async def test_token_refresh_saved(
    hass: HomeAssistant, fake_af: FakeAF, entry: MockConfigEntry
) -> None:
    fake_af.gym()
    fake_af.meter(HOME, 25, ROWS)
    entry =MockConfigEntry(
        domain=DOMAIN,
        unique_id=PHONE,
        data={**entry.data, CONF_EXPIRES_AT: time.time() - 10},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert fake_af.refresh_calls == 1
    assert entry.data[CONF_ACCESS_TOKEN] == "acc-2"
    assert entry.data["refresh_token"] == "ref-1"  # niet geroteerd -> oude bewaard
    assert hass.states.get("sensor.af_drukte_advies").state == "skip"


async def test_expired_session_starts_reauth(
    hass: HomeAssistant, fake_af: FakeAF, entry: MockConfigEntry
) -> None:
    fake_af.refresh_ok = False
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=PHONE, data={**entry.data, CONF_EXPIRES_AT: 0}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]

    # Opnieuw inloggen via de reauth-flow.
    fake_af.gym()
    fake_af.meter(HOME, 4, ROWS)
    flow_id = flows[0]["flow_id"]
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["step_id"] == "code"
    result = await hass.config_entries.flow.async_configure(flow_id, {"code": "123456"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_ACCESS_TOKEN] == "acc-1"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_add_club(
    hass: HomeAssistant, fake_af: FakeAF, entry: MockConfigEntry
) -> None:
    fake_af.gym()
    fake_af.meter(HOME, 4, ROWS)
    fake_af.meter("NL-1001", 30, ROWS)
    fake_af.mock.get(
        f"{API_BASE}/location/search",
        json=[
            {"locationNumber": HOME, "name": "Thuisclub", "distance": {"value": 0}},
            {"locationNumber": "NL-1001", "name": "Buurclub", "distance": {"value": 3.24}},
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    options = result["data_schema"].schema[CONF_CLUBS].config["options"]
    assert options == [{"value": "NL-1001", "label": "Buurclub (NL-1001, 3.2 km)"}]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CLUBS: ["NL-1001", HOME], CONF_SCAN_INTERVAL: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_CLUBS: ["NL-1001"],
        CONF_CLUB_NAMES: {"NL-1001": "Buurclub"},
        CONF_SCAN_INTERVAL: 120,
    }
    await hass.async_block_till_done()
    state = hass.states.get("sensor.af_drukte_nl_1001")
    assert state.state == "30"
    assert state.attributes["club"] == "Buurclub"
    assert hass.states.get("sensor.af_drukte_nl_1001_advies").state == "skip"
    assert entry.runtime_data.update_interval.total_seconds() == 120


async def test_one_club_failing_keeps_others(
    hass: HomeAssistant, fake_af: FakeAF, entry: MockConfigEntry
) -> None:
    fake_af.gym()
    fake_af.meter(HOME, 4, ROWS)
    fake_af.meter("NL-1001", None, ROWS, status=500)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PHONE,
        data=entry.data,
        options={CONF_CLUBS: ["NL-1001"], CONF_CLUB_NAMES: {}, CONF_SCAN_INTERVAL: 300},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.af_drukte").state == "4"
    assert hass.states.get("sensor.af_drukte_nl_1001").state == "unavailable"
