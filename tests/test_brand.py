"""Het eigen icoon wordt door HA geserveerd in plaats van de CDN."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

BRAND = Path(__file__).parents[1] / "custom_components" / "af_drukte" / "brand"


async def test_brand_icon_served(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    for image, file in [
        ("icon.png", "icon.png"),
        ("icon@2x.png", "icon@2x.png"),
        ("dark_icon.png", "icon.png"),  # valt terug op icon.png
    ]:
        resp = await client.get(f"/api/brands/integration/af_drukte/{image}")
        assert resp.status == 200, image
        assert await resp.read() == (BRAND / file).read_bytes(), image
