"""E2E tests for GoveeController — require a real device on the LAN."""

import asyncio
import socket

import pytest

from lightsync.govee import Color, GoveeController, GoveeDevice

DEVICE_IP = "192.168.178.29"
DEVICE_ID = "unknown"
SKU = "H6008"


def _is_device_reachable(ip: str, port: int = 4003, timeout: float = 1.0) -> bool:
    """Best-effort UDP reachability check — sends a byte and listens briefly."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(b"\x00", (ip, port))
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def reachable_device() -> GoveeDevice:
    """Session-scoped fixture; skips the whole module if device is unreachable."""
    if not _is_device_reachable(DEVICE_IP):
        pytest.skip(f"Govee device not reachable at {DEVICE_IP}:{4003}")
    return GoveeDevice(ip=DEVICE_IP, device_id=DEVICE_ID, sku=SKU)


@pytest.fixture(scope="session")
def controller() -> GoveeController:
    return GoveeController()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_discover(controller: GoveeController) -> None:
    """Discovery finds at least one device on the LAN."""
    devices = await controller.discover(timeout=5.0)
    assert len(devices) >= 1
    ips = [d.ip for d in devices]
    assert DEVICE_IP in ips


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_turn_on_off(
    controller: GoveeController, reachable_device: GoveeDevice
) -> None:
    """Device can be toggled off and back on."""
    await controller.turn(reachable_device, on=False)
    await asyncio.sleep(0.5)
    await controller.turn(reachable_device, on=True)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_set_brightness(
    controller: GoveeController, reachable_device: GoveeDevice
) -> None:
    """Brightness can be set to 50 % and back to 100 %."""
    await controller.set_brightness(reachable_device, 50)
    await asyncio.sleep(0.5)
    await controller.set_brightness(reachable_device, 100)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_set_color(
    controller: GoveeController, reachable_device: GoveeDevice
) -> None:
    """RGB color command is accepted without error."""
    await controller.set_color(reachable_device, Color(r=108, g=99, b=255))


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_set_color_temp(
    controller: GoveeController, reachable_device: GoveeDevice
) -> None:
    """Color temperature command is accepted without error."""
    await controller.set_color_temp(reachable_device, 4000)
