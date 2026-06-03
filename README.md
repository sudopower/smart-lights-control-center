# light-sync

Sync Govee LED lights to video and music via a slick local dashboard.

## Prerequisites

- Python 3.11+
- Govee H6008 (or compatible) with **LAN Control** enabled in the Govee Home app
- Device and host on the same LAN

## Quick start

```bash
pip install -e ".[dev]"
lightsync
# open http://localhost:8000
```

## Features

**Current**
- Local UDP control (no cloud dependency)
- Auto-discovery of Govee LAN devices
- Power toggle, brightness, RGB color, color temperature
- Real-time dashboard with preset colors

**Planned**
- Screen color capture → ambient sync
- Audio FFT → reactive lighting
- Scene recording and playback
- Multi-device groups

## Architecture

```
Dashboard (FastAPI)          govee.py
     │                          │
     │  REST API                │  Async UDP (port 4003)
     └──────────────────────────┴──────► Govee H6008
```

`GoveeController` speaks the Govee LAN UDP protocol directly — no cloud, no polling.
The FastAPI app wraps it with a REST API and serves the single-page dashboard.

## Contributing

PRs welcome. Run `make lint` and `make test` before opening one.
