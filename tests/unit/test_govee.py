"""Unit tests for GoveeController — no real device required."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lightsync.govee import Color, GoveeController, GoveeDevice

DEVICE_IP = "192.168.178.29"
DEVICE_ID = "AA:BB:CC:DD:EE:FF"
SKU = "H6008"


@pytest.fixture
def controller() -> GoveeController:
    return GoveeController()


@pytest.fixture
def device() -> GoveeDevice:
    return GoveeDevice(ip=DEVICE_IP, device_id=DEVICE_ID, sku=SKU)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_scan_response(ip: str = DEVICE_IP, device_id: str = DEVICE_ID, sku: str = SKU) -> bytes:
    """Build a well-formed Govee scan response."""
    return json.dumps(
        {"msg": {"cmd": "scan", "data": {"device": device_id, "sku": sku}}}
    ).encode()


# ── Discovery ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_parses_response(controller: GoveeController) -> None:
    """A valid scan response yields a correctly-parsed GoveeDevice."""
    response_data = _make_scan_response()

    # Patch the discovery listen endpoint and the broadcast helper.
    collected_devices = []

    async def fake_create_datagram_endpoint(protocol_factory, **kwargs):
        if "local_addr" in kwargs:
            # This is the listening endpoint — inject a fake protocol that
            # simulates receiving a device response.
            proto = protocol_factory()
            proto.datagram_received(response_data, (DEVICE_IP, 4002))
            collected_devices.extend(proto.devices)
            transport = MagicMock()
            transport.close = MagicMock()
            return transport, proto
        # Unexpected call
        raise RuntimeError("Unexpected endpoint creation")

    with (
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        loop = MagicMock()
        loop.create_datagram_endpoint = AsyncMock(side_effect=fake_create_datagram_endpoint)
        loop.run_in_executor = AsyncMock(return_value=None)
        mock_loop.return_value = loop

        devices = await controller.discover(timeout=0.01)

    assert len(devices) == 1
    assert devices[0].ip == DEVICE_IP
    assert devices[0].device_id == DEVICE_ID
    assert devices[0].sku == SKU


@pytest.mark.asyncio
async def test_discover_timeout(controller: GoveeController) -> None:
    """When no devices respond, discover returns an empty list."""

    async def fake_create_datagram_endpoint(protocol_factory, **kwargs):
        proto = protocol_factory()  # no datagram_received called
        transport = MagicMock()
        transport.close = MagicMock()
        return transport, proto

    with (
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        loop = MagicMock()
        loop.create_datagram_endpoint = AsyncMock(side_effect=fake_create_datagram_endpoint)
        loop.run_in_executor = AsyncMock(return_value=None)
        mock_loop.return_value = loop

        devices = await controller.discover(timeout=0.01)

    assert devices == []


@pytest.mark.asyncio
async def test_discover_ignores_malformed_responses(controller: GoveeController) -> None:
    """Malformed UDP payloads are silently skipped."""
    bad_payloads = [
        b"not json at all",
        b'{"msg": null}',
        b'{}',
        b'{"msg": {"cmd": "scan", "data": {}}}',  # missing device id
    ]

    async def fake_create_datagram_endpoint(protocol_factory, **kwargs):
        proto = protocol_factory()
        for payload in bad_payloads:
            proto.datagram_received(payload, (DEVICE_IP, 4002))
        transport = MagicMock()
        transport.close = MagicMock()
        return transport, proto

    with (
        patch("asyncio.get_running_loop") as mock_loop,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        loop = MagicMock()
        loop.create_datagram_endpoint = AsyncMock(side_effect=fake_create_datagram_endpoint)
        loop.run_in_executor = AsyncMock(return_value=None)
        mock_loop.return_value = loop

        devices = await controller.discover(timeout=0.01)

    assert devices == []


# ── Control commands ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_on_sends_correct_payload(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """turn(on=True) sends value=1."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.turn(device, on=True)
        mock_send.assert_awaited_once_with(DEVICE_IP, "turn", {"value": 1})


@pytest.mark.asyncio
async def test_turn_off_sends_correct_payload(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """turn(on=False) sends value=0."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.turn(device, on=False)
        mock_send.assert_awaited_once_with(DEVICE_IP, "turn", {"value": 0})


@pytest.mark.asyncio
async def test_set_brightness_sends_correct_payload(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """set_brightness sends the value unchanged when in range."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.set_brightness(device, 75)
        mock_send.assert_awaited_once_with(DEVICE_IP, "brightness", {"value": 75})


@pytest.mark.asyncio
async def test_set_brightness_clamps_to_range(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """Values >100 clamp to 100 and <1 clamp to 1."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.set_brightness(device, 150)
        mock_send.assert_awaited_with(DEVICE_IP, "brightness", {"value": 100})

        await controller.set_brightness(device, 0)
        mock_send.assert_awaited_with(DEVICE_IP, "brightness", {"value": 1})

        await controller.set_brightness(device, -5)
        mock_send.assert_awaited_with(DEVICE_IP, "brightness", {"value": 1})


@pytest.mark.asyncio
async def test_set_color_sends_correct_payload(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """set_color sends colorwc with the right RGB and zeroed kelvin."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.set_color(device, Color(r=255, g=0, b=128))
        mock_send.assert_awaited_once_with(
            DEVICE_IP,
            "colorwc",
            {"color": {"r": 255, "g": 0, "b": 128}, "colorTemInKelvin": 0},
        )


@pytest.mark.asyncio
async def test_set_color_temp_sends_correct_payload(
    controller: GoveeController, device: GoveeDevice
) -> None:
    """set_color_temp sends colorwc with the kelvin value and zeroed RGB."""
    with patch.object(controller, "_send", new_callable=AsyncMock) as mock_send:
        await controller.set_color_temp(device, 4000)
        mock_send.assert_awaited_once_with(
            DEVICE_IP,
            "colorwc",
            {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 4000},
        )
