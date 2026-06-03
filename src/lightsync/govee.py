"""Async Govee LAN UDP controller."""

import asyncio
import json
import logging
import socket
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 4001
DISCOVERY_LISTEN_PORT = 4002
CONTROL_PORT = 4003

BROADCAST_ADDRESSES = ["255.255.255.255", "239.255.255.250"]

SCAN_MESSAGE = json.dumps(
    {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
).encode()


@dataclass
class GoveeDevice:
    """A discovered Govee LAN device."""

    ip: str
    device_id: str
    sku: str


@dataclass
class Color:
    """RGB color (each channel 0-255)."""

    r: int
    g: int
    b: int


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collects scan responses from Govee devices."""

    def __init__(self) -> None:
        self.devices: list[GoveeDevice] = []
        self._seen: set[str] = set()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg = json.loads(data.decode())
            inner = msg.get("msg", {})
            if inner.get("cmd") != "scan":
                return
            payload = inner.get("data", {})
            ip = addr[0]
            device_id = payload.get("device", "")
            sku = payload.get("sku", "")
            if ip not in self._seen and device_id:
                self._seen.add(ip)
                self.devices.append(GoveeDevice(ip=ip, device_id=device_id, sku=sku))
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass

    def error_received(self, exc: Exception) -> None:
        logger.debug("Discovery error: %s", exc)


class GoveeController:
    """Async controller for Govee devices using the LAN UDP protocol.

    All control methods are fire-and-forget — Govee does not send ACKs.
    """

    async def discover(self, timeout: float = 5.0) -> list[GoveeDevice]:
        """Broadcast scan and collect responding devices.

        Listens on 0.0.0.0:4002 for device responses.
        """
        loop = asyncio.get_running_loop()
        protocol = _DiscoveryProtocol()

        listen_transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=("0.0.0.0", DISCOVERY_LISTEN_PORT),
        )

        # Raw socket for broadcast — asyncio's datagram endpoint doesn't expose
        # SO_BROADCAST easily, so we use a blocking send from a thread.
        def _broadcast() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(1)
                for addr in BROADCAST_ADDRESSES:
                    try:
                        sock.sendto(SCAN_MESSAGE, (addr, DISCOVERY_PORT))
                    except Exception as exc:
                        logger.debug("Broadcast to %s failed: %s", addr, exc)

        try:
            await loop.run_in_executor(None, _broadcast)
            await asyncio.sleep(timeout)
        finally:
            listen_transport.close()

        return protocol.devices

    async def turn(self, device: GoveeDevice, on: bool) -> None:
        """Power on (True) or off (False) a device."""
        await self._send(device.ip, "turn", {"value": 1 if on else 0})

    async def set_brightness(self, device: GoveeDevice, value: int) -> None:
        """Set brightness (1-100); values outside range are clamped."""
        clamped = max(1, min(100, value))
        await self._send(device.ip, "brightness", {"value": clamped})

    async def set_color(self, device: GoveeDevice, color: Color) -> None:
        """Set RGB color. Also zeroes colorTemInKelvin as required by protocol."""
        await self._send(
            device.ip,
            "colorwc",
            {"color": {"r": color.r, "g": color.g, "b": color.b}, "colorTemInKelvin": 0},
        )

    async def set_color_temp(self, device: GoveeDevice, kelvin: int) -> None:
        """Set color temperature (2000-9000 K)."""
        await self._send(
            device.ip,
            "colorwc",
            {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": kelvin},
        )

    async def _send(self, ip: str, cmd: str, data: dict) -> None:
        """Send a single UDP command to a device IP on port 4003."""
        payload = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()

        def _send_udp() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1)
                sock.sendto(payload, (ip, CONTROL_PORT))

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_udp)
