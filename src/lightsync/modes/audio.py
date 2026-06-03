"""Audio capture and analysis engine for real-time light sync."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np

from lightsync.govee import Color, GoveeController, GoveeDevice

logger = logging.getLogger(__name__)

# Frequency band boundaries (Hz)
_BASS_HZ = (20, 250)
_MID_HZ = (250, 4000)
_TREBLE_HZ = (4000, 20000)

# Min interval between UDP commands (seconds) → 30 cmd/s max
_MIN_CMD_INTERVAL = 1.0 / 30


@dataclass
class AudioSettings:
    """Configuration for the audio sync engine."""

    sensitivity: float = 1.0      # 0.5–2.0 — scales amplitude before mapping
    color_mode: str = "spectrum"  # "spectrum" | "pulse" | "bass"
    smoothing: float = 0.6        # 0.0–1.0 — temporal smoothing factor
    min_brightness: int = 5       # floor so the light never fully dies
    sample_rate: int = 44100
    chunk_size: int = 1024


@dataclass
class AudioFrame:
    """A single analysis snapshot."""

    rms: float       # overall amplitude 0.0–1.0
    bass: float      # low-freq energy 0.0–1.0
    mid: float       # mid-freq energy 0.0–1.0
    treble: float    # high-freq energy 0.0–1.0
    brightness: int  # computed 1–100
    color: Color     # color to send to the light

    def as_dict(self) -> dict:
        """Return JSON-serialisable representation."""
        return {
            "rms": round(self.rms, 4),
            "bass": round(self.bass, 4),
            "mid": round(self.mid, 4),
            "treble": round(self.treble, 4),
            "brightness": self.brightness,
            "color": {"r": self.color.r, "g": self.color.g, "b": self.color.b},
        }


def _band_energy(magnitudes: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    """RMS energy of FFT magnitudes within [lo, hi] Hz."""
    mask = (freqs >= lo) & (freqs < hi)
    band = magnitudes[mask]
    if band.size == 0:
        return 0.0
    energy = float(np.sqrt(np.mean(band**2)))
    return energy


def _spectrum_color(bass: float, mid: float, treble: float, brightness: int) -> Color:
    """Map dominant frequency band to a colour in the red-green-blue spectrum."""
    dominant = max(bass, mid, treble)
    if dominant == 0:
        return Color(r=brightness, g=brightness, b=brightness)

    # Weighted blend: bass→red/orange, mid→green/yellow, treble→blue/purple
    r = int(255 * bass / (dominant + 1e-9) * bass)
    g = int(255 * mid  / (dominant + 1e-9) * mid)
    b = int(255 * treble / (dominant + 1e-9) * treble)

    # Simpler: pick hue by dominant band
    if bass >= mid and bass >= treble:
        # Red-orange: mix red with a touch of green proportional to mid
        r = 255
        g = int(80 + 120 * mid)
        b = int(20 * treble)
    elif mid >= bass and mid >= treble:
        # Green-yellow
        r = int(80 + 120 * bass)
        g = 255
        b = int(40 * treble)
    else:
        # Blue-purple
        r = int(60 + 140 * bass)
        g = int(20 + 80 * mid)
        b = 255

    scale = brightness / 100.0
    return Color(
        r=max(0, min(255, int(r * scale))),
        g=max(0, min(255, int(g * scale))),
        b=max(0, min(255, int(b * scale))),
    )


def _pulse_color(brightness: int) -> Color:
    """Warm white (≈3000 K) that pulses with RMS."""
    scale = brightness / 100.0
    return Color(
        r=max(0, min(255, int(255 * scale))),
        g=max(0, min(255, int(197 * scale))),
        b=max(0, min(255, int(143 * scale))),
    )


def _bass_color(bass: float, brightness: int) -> Color:
    """Deep red on bass hit, dim purple at rest."""
    scale = brightness / 100.0
    r = max(0, min(255, int((180 + 75 * bass) * scale)))
    g = max(0, min(255, int(10 * scale)))
    b = max(0, min(255, int((40 + 60 * (1 - bass)) * scale)))
    return Color(r=r, g=g, b=b)


class AudioSync:
    """Captures system audio and drives a Govee light in real-time.

    Usage::

        sync = AudioSync(controller, device, AudioSettings())
        await sync.start()
        # ... later
        await sync.stop()
    """

    def __init__(
        self,
        controller: GoveeController,
        device: GoveeDevice,
        settings: AudioSettings,
        device_index: int | None = None,
    ) -> None:
        self._controller = controller
        self._device = device
        self._settings = settings
        self._device_index = device_index

        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=64)
        self._task: asyncio.Task | None = None
        self._stream = None  # sounddevice InputStream

        # Smoothed band values
        self._smooth_rms: float = 0.0
        self._smooth_bass: float = 0.0
        self._smooth_mid: float = 0.0
        self._smooth_treble: float = 0.0

        self._current_frame: AudioFrame = AudioFrame(
            rms=0.0, bass=0.0, mid=0.0, treble=0.0,
            brightness=settings.min_brightness,
            color=Color(r=0, g=0, b=0),
        )
        self._last_cmd_time: float = 0.0

    # ── Public interface ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Begin audio capture and light-drive loop."""
        if self._task and not self._task.done():
            return
        # Import here so the module can be imported without sounddevice installed
        import sounddevice as sd  # noqa: PLC0415

        loop = asyncio.get_running_loop()

        def _callback(indata: np.ndarray, frames: int, t, status) -> None:  # noqa: ANN001
            if status:
                logger.debug("sounddevice status: %s", status)
            chunk = indata[:, 0].copy()  # mono
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except asyncio.QueueFull:
                pass  # drop frame rather than block

        self._stream = sd.InputStream(
            samplerate=self._settings.sample_rate,
            channels=1,
            blocksize=self._settings.chunk_size,
            dtype="float32",
            device=self._device_index,
            callback=_callback,
        )
        self._stream.start()
        self._task = asyncio.create_task(self._run(), name="audio-sync")
        logger.info("AudioSync started (mode=%s)", self._settings.color_mode)

    async def stop(self) -> None:
        """Stop the capture loop and clean up the stream thread."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.debug("Error closing stream: %s", exc)
            self._stream = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("AudioSync stopped")

    @property
    def is_running(self) -> bool:
        """True if the capture loop is active."""
        return self._task is not None and not self._task.done()

    @property
    def current_frame(self) -> AudioFrame:
        """Latest analysis snapshot."""
        return self._current_frame

    # ── Class methods ─────────────────────────────────────────────────────────

    @classmethod
    def list_devices(cls) -> list[dict]:
        """Return sounddevice input device list."""
        import sounddevice as sd  # noqa: PLC0415

        devices = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({"index": i, "name": dev["name"], "channels": dev["max_input_channels"]})
        return devices

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Main async loop: drain queue, analyse, send to light."""
        while True:
            chunk: np.ndarray = await self._queue.get()
            frame = self._analyze(chunk)
            self._current_frame = frame

            now = time.monotonic()
            if now - self._last_cmd_time >= _MIN_CMD_INTERVAL:
                self._last_cmd_time = now
                try:
                    await self._controller.set_color(self._device, frame.color)
                    await self._controller.set_brightness(self._device, frame.brightness)
                except Exception as exc:
                    logger.debug("Light command failed: %s", exc)

    def _analyze(self, chunk: np.ndarray) -> AudioFrame:
        """Pure analysis: FFT the chunk, compute bands, apply smoothing, compute color.

        Args:
            chunk: 1-D float32 array of audio samples (normalised –1 to +1).

        Returns:
            An AudioFrame with smoothed values and the color/brightness to send.
        """
        s = self._settings
        n = len(chunk)

        # RMS amplitude
        raw_rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        raw_rms = min(1.0, raw_rms * s.sensitivity)

        # FFT — one-sided magnitude spectrum
        spectrum = np.abs(np.fft.rfft(chunk.astype(np.float64)))
        freqs = np.fft.rfftfreq(n, d=1.0 / s.sample_rate)

        # Normalise spectrum by n/2 so magnitudes are in [0, 1] range
        magnitudes = spectrum / (n / 2.0)

        raw_bass   = min(1.0, _band_energy(magnitudes, freqs, *_BASS_HZ)   * s.sensitivity)
        raw_mid    = min(1.0, _band_energy(magnitudes, freqs, *_MID_HZ)    * s.sensitivity)
        raw_treble = min(1.0, _band_energy(magnitudes, freqs, *_TREBLE_HZ) * s.sensitivity)

        # Temporal smoothing
        sm = s.smoothing
        self._smooth_rms    = self._smooth_rms    * sm + raw_rms    * (1 - sm)
        self._smooth_bass   = self._smooth_bass   * sm + raw_bass   * (1 - sm)
        self._smooth_mid    = self._smooth_mid    * sm + raw_mid    * (1 - sm)
        self._smooth_treble = self._smooth_treble * sm + raw_treble * (1 - sm)

        rms    = self._smooth_rms
        bass   = self._smooth_bass
        mid    = self._smooth_mid
        treble = self._smooth_treble

        brightness = max(s.min_brightness, min(100, int(rms * 100)))

        if s.color_mode == "pulse":
            color = _pulse_color(brightness)
        elif s.color_mode == "bass":
            brightness = max(s.min_brightness, min(100, int(bass * 100)))
            color = _bass_color(bass, brightness)
        else:  # "spectrum"
            color = _spectrum_color(bass, mid, treble, brightness)

        return AudioFrame(
            rms=rms, bass=bass, mid=mid, treble=treble,
            brightness=brightness, color=color,
        )
