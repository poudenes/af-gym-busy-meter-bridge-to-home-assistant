"""Gedeelde fixtures: een nagebootste Anytime Fitness-API."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.af_drukte.api import API_BASE, COGNITO_URL
from custom_components.af_drukte.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

HOME = "NL-0001"
PHONE = "+31612345678"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Laat HA custom_components laden."""
    return


def busy_meter(current: int | None, rows: list[tuple[str, int]]) -> dict[str, Any]:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "currentMemberCount": current,
        "weekDays": [
            {
                "weekDay": day,
                "averageUsages": [
                    {"startTime": start, "averageUsageValue": value} for start, value in rows
                ],
            }
            for day in days
        ],
    }


class FakeAF:
    """Houdt bij wat Cognito moet antwoorden en telt aanroepen."""

    def __init__(self, mock: AiohttpClientMocker) -> None:
        self.mock = mock
        self.code = "123456"
        self.refresh_ok = True
        self.refresh_calls = 0
        self.cognito_targets: list[str] = []
        mock.post(COGNITO_URL, side_effect=self._cognito)

    async def _cognito(self, method, url, data):
        body = json.loads(data)
        if "AuthFlow" in body:
            self.cognito_targets.append("InitiateAuth")
            return AiohttpClientMockResponse(method, url, json={"Session": "sess-1"})
        if "ChallengeResponses" in body:
            self.cognito_targets.append("RespondToAuthChallenge")
            if body["ChallengeResponses"]["SMS_OTP_CODE"] != self.code:
                return AiohttpClientMockResponse(
                    method, url, status=400, json={"__type": "CodeMismatchException"}
                )
            return AiohttpClientMockResponse(
                method,
                url,
                json={
                    "AuthenticationResult": {
                        "AccessToken": "acc-1",
                        "RefreshToken": "ref-1",
                        "ExpiresIn": 3600,
                    }
                },
            )
        if "RefreshToken" in body:
            self.refresh_calls += 1
            if not self.refresh_ok:
                return AiohttpClientMockResponse(
                    method, url, status=400, json={"__type": "NotAuthorizedException"}
                )
            return AiohttpClientMockResponse(
                method,
                url,
                json={"AuthenticationResult": {"AccessToken": "acc-2", "ExpiresIn": 3600}},
            )
        raise AssertionError(f"onverwachte Cognito-aanroep: {body}")

    def gym(self) -> None:
        self.mock.get(
            f"{API_BASE}/me/user/my-gym",
            json={
                "clubProfile": {
                    "afNumber": HOME,
                    "name": "Thuisclub",
                    "coordinates": {"latitude": 52.0, "longitude": 5.0},
                }
            },
        )

    def meter(self, af_number: str, current: int | None, rows, status: int = 200) -> None:
        self.mock.get(
            f"{API_BASE}/clubs/{af_number}/busy-meter",
            status=status,
            json=busy_meter(current, rows),
        )


@pytest.fixture
def fake_af(aioclient_mock: AiohttpClientMocker) -> FakeAF:
    return FakeAF(aioclient_mock)


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=PHONE,
        title="Anytime Fitness Thuisclub",
        data={
            CONF_PHONE: PHONE,
            CONF_ACCESS_TOKEN: "acc-1",
            CONF_REFRESH_TOKEN: "ref-1",
            CONF_EXPIRES_AT: time.time() + 3600,
        },
    )
