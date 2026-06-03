"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def govee_device():
    """A dummy GoveeDevice for use in tests."""
    from lightsync.govee import GoveeDevice

    return GoveeDevice(ip="192.168.178.29", device_id="AA:BB:CC:DD:EE:FF", sku="H6008")
