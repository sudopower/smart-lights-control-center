# light·sync

Sync Govee LED lights to music and video via a local dashboard — no cloud, no latency.

## Prerequisites

- Python 3.11+
- Govee light with **LAN Control** enabled (Govee Home app → Device → Settings → LAN Control)
- Device and host on the same Wi-Fi network

## Quick start

```bash
git clone https://github.com/sudopower/smart-lights-control-center.git
cd smart-lights-control-center
make install
make run
# open http://localhost:8000
```

## Features

### Manual control
- Auto-discovers Govee lights on your LAN (no IP config needed)
- Power toggle, brightness, RGB color picker, color temperature (2000K–9000K)
- Color presets: warm white, cool white, red, green, blue, purple, orange
- White tones automatically use the color-temp API for accurate reproduction

### Audio sync
Real-time FFT analysis drives the light from mic or system audio input.

| Mode | Behavior |
|------|----------|
| **Spectrum** | Bass → red/orange · Mid → green/yellow · Treble → blue/purple |
| **Pulse** | Warm white, brightness pulses with volume |
| **Bass** | Deep red on bass hits, dim purple at rest |

- Sensitivity and smoothing controls
- Live Bass / Mid / Treble visualizer bars in the dashboard
- Up to 30 light updates per second

**System audio on macOS:** install [BlackHole 2ch](https://existingcircuits.com/sw/BlackHole), create a Multi-Output Device in Audio MIDI Setup (BlackHole + your speakers), set it as system output, then select BlackHole as the input device in light·sync.

### Planned
- Screen capture → ambient video sync (YouTube, movies)
- Scene recording and playback
- Multi-device groups

## Architecture

```
Browser
  │  REST + WebSocket
  ▼
FastAPI dashboard (app.py)
  │
  ├── GoveeController (govee.py)
  │     └── Async UDP · port 4003 · Govee LAN API
  │
  └── AudioSync (modes/audio.py)
        └── sounddevice → numpy FFT → Color + Brightness
```

All communication with the light is local UDP — no Govee cloud account required, sub-20ms command latency.

## Development

```bash
make install    # create .venv and install deps
make run        # start dashboard with --reload at http://localhost:8000
make test       # unit tests (mocked, no hardware needed)
make test-e2e   # integration tests (requires light on LAN)
make test-all   # everything
make lint       # ruff check
make fmt        # ruff format
```

Tests use mocked UDP sockets and mocked sounddevice — no hardware required for `make test`.
E2E tests auto-skip if the device is not reachable.

## Contributing

PRs welcome. Run `make lint && make test` before opening one.
