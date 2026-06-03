"""FastAPI dashboard for light-sync."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lightsync.govee import Color, GoveeController, GoveeDevice

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# ── Request models ────────────────────────────────────────────────────────────


class ColorPayload(BaseModel):
    r: int
    g: int
    b: int


class BrightnessPayload(BaseModel):
    value: int


class PowerPayload(BaseModel):
    on: bool


class ColorTempPayload(BaseModel):
    kelvin: int


# ── App factory ───────────────────────────────────────────────────────────────


def create_app(controller: GoveeController | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="light-sync", version="0.1.0")
    ctrl = controller or GoveeController()

    # In-memory state: ip → {device, state}
    _registry: dict[str, dict[str, Any]] = {}

    def _get_device(ip: str) -> GoveeDevice:
        entry = _registry.get(ip)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Device {ip} not found")
        return entry["device"]

    # ── API routes ────────────────────────────────────────────────────────────

    @app.get("/api/devices")
    async def list_devices() -> list[dict[str, Any]]:
        """Trigger discovery and return found devices."""
        devices = await ctrl.discover(timeout=3.0)
        for dev in devices:
            if dev.ip not in _registry:
                _registry[dev.ip] = {
                    "device": dev,
                    "state": {
                        "on": True,
                        "brightness": 100,
                        "color": {"r": 255, "g": 255, "b": 255},
                        "kelvin": 0,
                    },
                }
        return [
            {
                "ip": ip,
                "device_id": e["device"].device_id,
                "sku": e["device"].sku,
                "state": e["state"],
            }
            for ip, e in _registry.items()
        ]

    @app.get("/api/devices/{ip}/state")
    async def get_state(ip: str) -> dict[str, Any]:
        """Return cached last-known state for a device."""
        _get_device(ip)
        return _registry[ip]["state"]

    @app.post("/api/devices/{ip}/color")
    async def set_color(ip: str, payload: ColorPayload) -> dict[str, str]:
        """Set RGB color."""
        device = _get_device(ip)
        await ctrl.set_color(device, Color(r=payload.r, g=payload.g, b=payload.b))
        _registry[ip]["state"]["color"] = {"r": payload.r, "g": payload.g, "b": payload.b}
        _registry[ip]["state"]["kelvin"] = 0
        return {"status": "ok"}

    @app.post("/api/devices/{ip}/brightness")
    async def set_brightness(ip: str, payload: BrightnessPayload) -> dict[str, str]:
        """Set brightness (1-100)."""
        device = _get_device(ip)
        await ctrl.set_brightness(device, payload.value)
        _registry[ip]["state"]["brightness"] = max(1, min(100, payload.value))
        return {"status": "ok"}

    @app.post("/api/devices/{ip}/power")
    async def set_power(ip: str, payload: PowerPayload) -> dict[str, str]:
        """Power on or off."""
        device = _get_device(ip)
        await ctrl.turn(device, payload.on)
        _registry[ip]["state"]["on"] = payload.on
        return {"status": "ok"}

    @app.post("/api/devices/{ip}/color-temp")
    async def set_color_temp(ip: str, payload: ColorTempPayload) -> dict[str, str]:
        """Set color temperature in Kelvin."""
        device = _get_device(ip)
        await ctrl.set_color_temp(device, payload.kelvin)
        _registry[ip]["state"]["kelvin"] = payload.kelvin
        _registry[ip]["state"]["color"] = {"r": 0, "g": 0, "b": 0}
        return {"status": "ok"}

    # ── Static files ──────────────────────────────────────────────────────────

    @app.get("/")
    async def index() -> FileResponse:
        """Serve the dashboard."""
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def main() -> None:
    """Entry point for the `lightsync` CLI command."""
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "lightsync.dashboard.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
