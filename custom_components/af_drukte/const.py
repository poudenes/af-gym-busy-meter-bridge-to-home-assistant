"""Constanten voor de Anytime Fitness drukte-integratie."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "af_drukte"

CONF_PHONE: Final = "phone"
CONF_CODE: Final = "code"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_EXPIRES_AT: Final = "expires_at"
CONF_CLUBS: Final = "clubs"
CONF_CLUB_NAMES: Final = "club_names"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 300  # seconden
MIN_SCAN_INTERVAL: Final = 60

# Verhouding live / gebruikelijk aantal voor dit uur -> advies.
VERDICT_BANDS: Final = (
    (0.50, "go-now"),
    (0.85, "good-time"),
    (1.15, "normal"),
    (1.50, "wait"),
)
VERDICT_MESSAGES: Final = {
    "go-now": "Veel rustiger dan normaal. Ga nu!",
    "good-time": "Rustiger dan normaal. Goed moment om te gaan.",
    "normal": "Ongeveer normaal voor dit uur.",
    "wait": "Drukker dan normaal. Misschien een uurtje wachten.",
    "skip": "Uitzonderlijk druk. Sla het over als het kan.",
    "no-live-data": "Deze club heeft nu geen live drukte.",
    "no-baseline": "Geen gebruikelijk aantal bekend voor dit uur.",
}
VERDICTS: Final = list(VERDICT_MESSAGES)
