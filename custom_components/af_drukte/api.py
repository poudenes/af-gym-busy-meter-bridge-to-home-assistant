"""Async client voor de (onofficiële) Anytime Fitness app-API.

Gebaseerd op af-unofficial-mcp-server van Sajush Arukat (MIT-licentie):
https://github.com/Sajush00/af-unofficial-mcp-server

Let op: dit is de privé-API van de AF-app en kan zonder waarschuwing veranderen.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import aiohttp

from .const import VERDICT_BANDS, VERDICT_MESSAGES

COGNITO_URL = "https://cognito-idp.us-east-1.amazonaws.com/"
COGNITO_CLIENT_ID = "r56fk5c6c5gfaegh5j673hdeq"
API_BASE = "https://api.sebrands.com/mobile/api"
API_HEADERS = {"Api-Version": "5.0", "Accept": "application/json"}
TIMEOUT = aiohttp.ClientTimeout(total=30)


class AFError(Exception):
    """Algemene fout bij het praten met Anytime Fitness."""


class AFConnectionError(AFError):
    """Geen (geldig) antwoord van de server."""


class AFAuthError(AFError):
    """Inloggen nodig: sessie ontbreekt, is verlopen of de code klopt niet."""


class AFApiError(AFError):
    """De API antwoordde met een foutstatus."""

    def __init__(self, status: int, detail: str, url: str) -> None:
        super().__init__(f"{status} van {url}: {detail}")
        self.status = status


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: list[tuple[str, str]] | dict[str, Any] | None = None,
    data: bytes | None = None,
) -> Any:
    try:
        async with session.request(
            method, url, headers=headers, params=params, data=data, timeout=TIMEOUT
        ) as resp:
            body = await resp.read()
            if resp.status >= 400:
                raise AFApiError(resp.status, body.decode(errors="replace")[:300], url)
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise AFConnectionError(f"Netwerkfout voor {url}: {exc}") from exc
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError as exc:
        raise AFApiError(resp.status, "antwoord was geen geldige JSON", url) from exc


async def _cognito(
    session: aiohttp.ClientSession, operation: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        response = await _request(
            session,
            "POST",
            COGNITO_URL,
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"AWSCognitoIdentityProviderService.{operation}",
            },
            data=json.dumps(body).encode(),
        )
    except AFApiError as exc:
        # Cognito geeft 400 bij een foute code, verlopen sessie, onbekend nummer.
        if exc.status in (400, 401, 403):
            raise AFAuthError(str(exc)) from exc
        raise
    return response if isinstance(response, dict) else {}


def _tokens(result: dict[str, Any], refresh_token: str | None = None) -> dict[str, Any]:
    return {
        "access_token": result["AccessToken"],
        "refresh_token": result.get("RefreshToken") or refresh_token,
        "expires_at": time.time() + float(result.get("ExpiresIn", 3600)),
    }


async def request_sms_code(session: aiohttp.ClientSession, phone: str) -> str:
    """Start sms-login; geeft de Cognito-sessie terug die bij de code hoort."""
    response = await _cognito(
        session,
        "InitiateAuth",
        {
            "AuthFlow": "USER_AUTH",
            "AuthParameters": {"USERNAME": phone, "PREFERRED_CHALLENGE": "SMS_OTP"},
            "ClientId": COGNITO_CLIENT_ID,
            "ClientMetadata": {"deliveryChannel": "sms"},
        },
    )
    if not response.get("Session"):
        raise AFAuthError("Cognito startte geen sms-verificatie")
    return response["Session"]


async def verify_sms_code(
    session: aiohttp.ClientSession, phone: str, cognito_session: str, code: str
) -> dict[str, Any]:
    """Rond de sms-login af; geeft access/refresh-token en verlooptijd terug."""
    response = await _cognito(
        session,
        "RespondToAuthChallenge",
        {
            "ChallengeName": "SMS_OTP",
            "ClientId": COGNITO_CLIENT_ID,
            "Session": cognito_session,
            "ChallengeResponses": {"USERNAME": phone, "SMS_OTP_CODE": code},
        },
    )
    result = response.get("AuthenticationResult")
    if not result:
        raise AFAuthError("Sms-verificatie mislukt")
    return _tokens(result)


class AFClient:
    """Ingelogde client; ververst het access-token zelf vlak voor het verloopt."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: dict[str, Any],
        on_tokens: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session = session
        self._tokens = dict(tokens)
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()

    async def _access_token(self, *, force: bool = False) -> str:
        async with self._lock:
            if force or time.time() > float(self._tokens.get("expires_at", 0)) - 60:
                refresh = self._tokens.get("refresh_token")
                if not refresh:
                    raise AFAuthError("Geen refresh-token; opnieuw inloggen nodig")
                response = await _cognito(
                    self._session,
                    "GetTokensFromRefreshToken",
                    {"RefreshToken": refresh, "ClientId": COGNITO_CLIENT_ID},
                )
                result = response.get("AuthenticationResult")
                if not result:
                    raise AFAuthError("Refresh-token verlopen; opnieuw inloggen nodig")
                self._tokens = _tokens(result, refresh)
                if self._on_tokens:
                    self._on_tokens(dict(self._tokens))
            return str(self._tokens["access_token"])

    async def _get(
        self, path: str, params: list[tuple[str, str]] | dict[str, Any] | None = None
    ) -> Any:
        url = f"{API_BASE}/{path}"
        for attempt in (0, 1):
            token = await self._access_token(force=attempt == 1)
            try:
                return await _request(
                    self._session,
                    "GET",
                    url,
                    headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
                    params=params,
                )
            except AFApiError as exc:
                if exc.status != 401:
                    raise
                if attempt == 1:
                    raise AFAuthError(str(exc)) from exc
                # 401 met een nog geldig lijkend token: één keer forceren te verversen.
        raise AFError("onbereikbaar")  # pragma: no cover

    async def home_gym(self) -> dict[str, Any]:
        """Profiel van de thuisclub (afNumber, name, coordinates, ...)."""
        data = await self._get("me/user/my-gym")
        return data["clubProfile"] if isinstance(data, dict) and "clubProfile" in data else data

    async def busy_meter(self, af_number: str) -> dict[str, Any]:
        """Live aantal + weekgemiddelden voor één club."""
        return await self._get(f"clubs/{af_number}/busy-meter")

    async def nearby(
        self, latitude: float, longitude: float, radius_km: int = 25, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Clubs in de buurt, dichtstbijzijnde eerst."""
        results = await self._get(
            "location/search",
            {
                "latitude": latitude,
                "longitude": longitude,
                "unitSystem": "Metric",
                "radius": radius_km,
                "page": 1,
                "pageSize": limit,
            },
        )
        return [
            {
                "af_number": club["locationNumber"],
                "name": club["name"],
                "distance_km": round((club.get("distance") or {}).get("value", 0), 1),
            }
            for club in results or []
        ]


def summarize(data: dict[str, Any], moment: datetime) -> dict[str, Any]:
    """Live drukte, advies en gebruikelijke aantallen voor de rest van vandaag."""
    usages: list[dict[str, Any]] = []
    weekday = moment.strftime("%A")
    for day in data.get("weekDays") or []:
        if day.get("weekDay") == weekday:
            usages = sorted(day.get("averageUsages") or [], key=lambda u: u["startTime"])
            break
    count = data.get("currentMemberCount")
    typical = next(
        (u["averageUsageValue"] for u in usages if int(u["startTime"][:2]) == moment.hour),
        None,
    )
    if count is None:
        verdict, ratio = "no-live-data", None
    elif not typical:
        verdict, ratio = "no-baseline", None
    else:
        ratio = count / typical
        verdict = next((name for ceiling, name in VERDICT_BANDS if ratio <= ceiling), "skip")
    return {
        "current": count,
        "typical": typical,
        "ratio": None if ratio is None else round(ratio, 2),
        "verdict": verdict,
        "verdict_message": VERDICT_MESSAGES[verdict],
        "rest_of_day": [
            {"hour": u["startTime"][:5], "typicalCount": u["averageUsageValue"]}
            for u in usages
            if int(u["startTime"][:2]) >= moment.hour
        ],
        "updated": moment.isoformat(timespec="minutes"),
    }
