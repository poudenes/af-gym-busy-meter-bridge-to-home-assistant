"""Anytime Fitness drukte -> Home Assistant bridge.

Start de onofficiële af-mcp server via stdio, roept de tool `occupancy` aan
voor je thuisclub (en optioneel extra clubs) en zet het resultaat als sensor
in Home Assistant via de REST API.

Testen zonder te pushen:  python bridge.py --test
"""
import asyncio
import json
import logging
import os
import re
import sys

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def env(name, default=""):
    """Lees AF_<naam> (globale env) of anders <naam>."""
    return (os.environ.get(f"AF_{name}") or os.environ.get(name) or default).strip()


HA_URL = env("HA_URL").rstrip("/")
HA_TOKEN = env("HA_TOKEN")
INTERVAL = int(env("INTERVAL", "300"))
CLUBS = [c.strip() for c in os.environ.get("AF_CLUBS", "").split(",") if c.strip()]
AF_MCP_BIN = os.environ.get("AF_MCP_BIN", "/app/af/.venv/bin/af-mcp")
TEST = "--test" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("af-bridge")
logging.getLogger("httpx").setLevel(logging.WARNING)


def field(obj, *names, default=None):
    """Lees een attribuut ongeacht camelCase/snake_case (verschilt per mcp-versie)."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def tool_text(result) -> str:
    structured = field(result, "structuredContent", "structured_content")
    if structured:
        return json.dumps(structured, ensure_ascii=False)
    return "\n".join(c.text for c in (field(result, "content") or []) if getattr(c, "type", "") == "text")


def parse(result, text: str) -> dict:
    """Occupancy-antwoord als dict (structuredContent of JSON-tekst)."""
    structured = field(result, "structuredContent", "structured_content")
    if isinstance(structured, dict) and "currentMemberCount" in structured:
        return structured
    try:
        return json.loads(text)
    except ValueError:
        return {}


def entity_for(club):
    if not club:
        return "sensor.af_drukte"
    return "sensor.af_drukte_" + re.sub(r"[^a-z0-9]+", "_", club.lower()).strip("_")


async def push(http, entity, state, attributes):
    r = await http.post(
        f"{HA_URL}/api/states/{entity}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
        json={"state": state, "attributes": attributes},
    )
    r.raise_for_status()


async def fetch():
    """Haal occupancy op voor alle clubs; geeft lijst (club, data) terug."""
    out = []
    params = StdioServerParameters(command=AF_MCP_BIN, args=[], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for club in [None, *CLUBS]:
                result = await session.call_tool("occupancy", {"club": club} if club else {})
                text = tool_text(result)
                if TEST:
                    print(f"\n=== {club or 'thuisclub'} ===\n{text}\n")
                    continue
                if field(result, "isError", "is_error", default=False):
                    log.warning("AF-fout voor %s: %s", club or "thuisclub", text)
                    continue
                data = parse(result, text)
                if "currentMemberCount" not in data:
                    log.warning("onverwacht antwoord voor %s: %s", club or "thuisclub", text[:300])
                    continue
                out.append((club, data))
    return out


async def publish(http, club, data):
    entity = entity_for(club)
    name = data.get("name") or club or "thuisclub"
    await push(http, entity, data["currentMemberCount"], {
        "friendly_name": f"AF {name} drukte",
        "unit_of_measurement": "personen",
        "state_class": "measurement",
        "icon": "mdi:weight-lifter",
        "club": name,
        "af_number": data.get("afNumber"),
        "typical_count": data.get("typicalCount"),
        "ratio": data.get("ratio"),
        "verdict": data.get("verdict"),
        "verdict_message": data.get("verdictMessage"),
        "rest_of_day": data.get("restOfDay", []),
        "updated": data.get("timestamp"),
    })
    await push(http, entity + "_normaal", data.get("typicalCount", "unknown"), {
        "friendly_name": f"AF {name} normaal",
        "unit_of_measurement": "personen",
        "state_class": "measurement",
        "icon": "mdi:chart-bell-curve",
    })
    await push(http, entity + "_advies", data.get("verdict", "unknown"), {
        "friendly_name": f"AF {name} advies",
        "icon": "mdi:run-fast",
        "message": data.get("verdictMessage"),
    })
    log.info("%s = %s (normaal %s, %s)", entity, data["currentMemberCount"],
             data.get("typicalCount"), data.get("verdict"))


def explain(exc) -> str:
    """Pak de echte fout(en) uit een ExceptionGroup."""
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(explain(e) for e in exc.exceptions)
    if isinstance(exc, httpx.HTTPStatusError):
        r = exc.response
        hint = " -> token ongeldig" if r.status_code == 401 else ""
        return f"HA antwoordde {r.status_code} op {r.request.url}{hint}"
    return f"{type(exc).__name__}: {exc}"


async def main():
    if not TEST and not (HA_URL and HA_TOKEN):
        sys.exit("HA_URL en HA_TOKEN moeten gezet zijn")
    log.info("HA_URL=%s, tokenlengte=%d, interval=%ss", HA_URL, len(HA_TOKEN), INTERVAL)
    async with httpx.AsyncClient(timeout=20) as http:
        while True:
            try:
                clubs = await fetch()
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                log.error("ophalen bij AF mislukt: %s", explain(exc))
                clubs = []
            for club, data in clubs:
                try:
                    await publish(http, club, data)
                except Exception as exc:
                    log.error("pushen naar HA mislukt: %s", explain(exc))
            if TEST:
                return
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
