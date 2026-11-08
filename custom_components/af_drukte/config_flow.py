"""Config flow: inloggen met telefoonnummer + sms-code, en opties."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AFAuthError, AFClient, AFError, request_sms_code, verify_sms_code
from .const import (
    CONF_CLUB_NAMES,
    CONF_CLUBS,
    CONF_CODE,
    CONF_PHONE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import AFConfigEntry

_LOGGER = logging.getLogger(__name__)


def normalize_phone(value: str) -> str | None:
    """Maak er een E.164-nummer van; 06... wordt +316...."""
    phone = re.sub(r"[\s\-().]", "", value)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    elif phone.startswith("0"):
        phone = "+31" + phone[1:]
    return phone if re.fullmatch(r"\+\d{8,15}", phone) else None


class AFConfigFlow(ConfigFlow, domain=DOMAIN):
    """Inlogflow voor een Anytime Fitness-account."""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str = ""
        self._cognito_session: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: AFConfigEntry) -> AFOptionsFlow:
        return AFOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Stap 1: telefoonnummer van het AF-account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = normalize_phone(user_input[CONF_PHONE])
            if phone is None:
                errors[CONF_PHONE] = "invalid_phone"
            else:
                await self.async_set_unique_id(phone)
                self._abort_if_unique_id_configured()
                self._phone = phone
                errors = await self._send_code()
                if not errors:
                    return await self.async_step_code()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PHONE): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.TEL)
                        )
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def _send_code(self) -> dict[str, str]:
        try:
            self._cognito_session = await request_sms_code(
                async_get_clientsession(self.hass), self._phone
            )
        except AFAuthError:
            return {"base": "unknown_account"}
        except AFError:
            _LOGGER.exception("Sms-code aanvragen mislukt")
            return {"base": "cannot_connect"}
        return {}

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Stap 2: sms-code invullen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                tokens = await verify_sms_code(
                    session, self._phone, self._cognito_session, user_input[CONF_CODE].strip()
                )
                home = await AFClient(session, tokens).home_gym()
            except AFAuthError:
                errors["base"] = "invalid_code"
            except AFError:
                _LOGGER.exception("Inloggen bij Anytime Fitness mislukt")
                errors["base"] = "cannot_connect"
            else:
                if self.source == "reauth":
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=tokens
                    )
                return self.async_create_entry(
                    title=f"Anytime Fitness {home.get('name') or home.get('afNumber')}",
                    data={CONF_PHONE: self._phone, **tokens},
                )
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            description_placeholders={"phone": self._phone},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Sessie verlopen: opnieuw inloggen met hetzelfde nummer."""
        self._phone = entry_data[CONF_PHONE]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._send_code()
            if not errors:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"phone": self._phone},
            errors=errors,
        )


class AFOptionsFlow(OptionsFlowWithReload):
    """Extra clubs en interval kiezen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry: AFConfigEntry = self.config_entry
        current: list[str] = entry.options.get(CONF_CLUBS, [])
        names: dict[str, str] = dict(entry.options.get(CONF_CLUB_NAMES, {}))

        nearby: list[dict[str, Any]] = []
        home_number = None
        if entry.state is ConfigEntryState.LOADED:
            coordinator = entry.runtime_data
            home = coordinator.home or {}
            home_number = home.get("afNumber")
            coords = home.get("coordinates") or {}
            if coords.get("latitude") is not None:
                try:
                    nearby = await coordinator.client.nearby(
                        coords["latitude"], coords["longitude"]
                    )
                except AFError as exc:
                    _LOGGER.warning("Clubs in de buurt ophalen mislukt: %s", exc)
        for club in nearby:
            names.setdefault(club["af_number"], club["name"])

        if user_input is not None:
            clubs = [c.strip().upper() for c in user_input[CONF_CLUBS] if c.strip()]
            clubs = [c for c in dict.fromkeys(clubs) if c != home_number]
            return self.async_create_entry(
                data={
                    CONF_CLUBS: clubs,
                    CONF_CLUB_NAMES: {c: names[c] for c in clubs if c in names},
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }
            )

        options = [
            SelectOptionDict(
                value=club["af_number"],
                label=f"{club['name']} ({club['af_number']}, {club['distance_km']} km)",
            )
            for club in nearby
            if club["af_number"] != home_number
        ]
        listed = {o["value"] for o in options}
        options += [
            SelectOptionDict(value=c, label=f"{names.get(c, c)} ({c})")
            for c in current
            if c not in listed
        ]
        schema = vol.Schema(
            {
                vol.Optional(CONF_CLUBS, default=current): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True, custom_value=True)
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=3600,
                        step=30,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
