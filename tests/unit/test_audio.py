"""Unit tests for the audio analysis engine (no real audio hardware)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub out sounddevice before importing audio.py so no hardware is needed
# ---------------------------------------------------------------------------

_sd_stub = types.ModuleType("sounddevice")
_sd_stub.InputStream = MagicMock()
_sd_stub.query_devices = MagicMock(return_value=[
    {"name": "Built-in Microphone", "max_input_channels": 1},
    {"name": "BlackHole 2ch",        "max_input_channels": 2},
])
sys.modules.setdefault("sounddevice", _sd_stub)

from lightsync.modes.audio import (  # noqa: E402
    AudioFrame,
    AudioSettings,
    AudioSync,
    _pulse_color,
    _spectrum_color,
)
from lightsync.govee import Color, GoveeController, GoveeDevice  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sync(settings: AudioSettings | None = None) -> AudioSync:
    ctrl = MagicMock(spec=GoveeController)
    device = GoveeDevice(ip="192.168.1.10", device_id="AA:BB", sku="H6199")
    s = settings or AudioSettings(smoothing=0.0)  # no smoothing for determinism
    return AudioSync(controller=ctrl, device=device, settings=s)


def _sine(freq_hz: float, sample_rate: int = 44100, chunk_size: int = 1024) -> np.ndarray:
    """Generate a mono sine wave at freq_hz."""
    t = np.arange(chunk_size) / sample_rate
    return np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def _silence(chunk_size: int = 1024) -> np.ndarray:
    return np.zeros(chunk_size, dtype=np.float32)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeSilence:
    def test_rms_is_zero(self) -> None:
        sync = _make_sync()
        frame = sync._analyze(_silence())
        assert frame.rms == pytest.approx(0.0, abs=1e-6)

    def test_brightness_is_min(self) -> None:
        sync = _make_sync()
        frame = sync._analyze(_silence())
        assert frame.brightness == AudioSettings().min_brightness


class TestAnalyzeBassHeavy:
    def test_bass_dominates(self) -> None:
        sync = _make_sync(AudioSettings(smoothing=0.0, sensitivity=3.0))
        chunk = _sine(100)  # 100 Hz → bass band
        frame = sync._analyze(chunk)
        assert frame.bass >= frame.mid
        assert frame.bass >= frame.treble
        assert frame.bass > 0.0


class TestSpectrumColorMode:
    def test_bass_gives_warm_color(self) -> None:
        """Bass-dominant input should produce a reddish/orange color."""
        # bass=1, mid=0, treble=0 → red channel dominant
        color = _spectrum_color(bass=1.0, mid=0.0, treble=0.0, brightness=80)
        assert color.r > color.b
        assert color.r > color.g or color.g > color.b  # warm side

    def test_treble_gives_cool_color(self) -> None:
        """Treble-dominant input should produce a bluish color."""
        color = _spectrum_color(bass=0.0, mid=0.0, treble=1.0, brightness=80)
        assert color.b > color.r or color.b > 0


class TestPulseMode:
    def test_gives_near_white(self) -> None:
        color = _pulse_color(brightness=100)
        # Warm white: R≥G≥B and all channels high
        assert color.r >= color.g >= color.b
        assert color.r > 200

    def test_pulse_mode_end_to_end(self) -> None:
        sync = _make_sync(AudioSettings(smoothing=0.0, color_mode="pulse"))
        chunk = _sine(440)
        frame = sync._analyze(chunk)
        # Pulse mode → near-white (r≥g≥b)
        assert frame.color.r >= frame.color.g >= frame.color.b


class TestSensitivity:
    def test_higher_sensitivity_raises_brightness(self) -> None:
        chunk = _sine(440) * 0.1  # quiet signal
        low_sync  = _make_sync(AudioSettings(smoothing=0.0, sensitivity=0.5))
        high_sync = _make_sync(AudioSettings(smoothing=0.0, sensitivity=2.0))
        low_frame  = low_sync._analyze(chunk)
        high_frame = high_sync._analyze(chunk)
        assert high_frame.brightness >= low_frame.brightness


class TestSmoothing:
    def test_smoothing_dampens_spike(self) -> None:
        """With high smoothing the response to a sudden loud signal is attenuated."""
        chunk_loud   = _sine(440) * 1.0
        chunk_silence = _silence()

        # No smoothing: immediate response
        raw_sync = _make_sync(AudioSettings(smoothing=0.0, sensitivity=1.0))
        raw_sync._analyze(chunk_silence)   # prime state
        frame_raw = raw_sync._analyze(chunk_loud)

        # High smoothing: responds slowly
        smooth_sync = _make_sync(AudioSettings(smoothing=0.9, sensitivity=1.0))
        smooth_sync._analyze(chunk_silence)   # prime state
        frame_smooth = smooth_sync._analyze(chunk_loud)

        assert frame_smooth.rms < frame_raw.rms


class TestListDevices:
    def test_returns_input_devices_only(self) -> None:
        devs = AudioSync.list_devices()
        assert isinstance(devs, list)
        for d in devs:
            assert "index" in d
            assert "name" in d
