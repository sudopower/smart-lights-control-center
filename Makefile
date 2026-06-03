VENV     ?= .venv
PYTHON   ?= $(VENV)/bin/python
PIP      ?= $(VENV)/bin/pip
PYTEST   ?= $(VENV)/bin/pytest
RUFF     ?= $(VENV)/bin/ruff
UVICORN  ?= $(VENV)/bin/uvicorn

.PHONY: install test test-e2e test-all lint fmt run

install:
	python3.13 -m venv $(VENV)
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) tests/unit -v

test-e2e:
	$(PYTEST) tests/e2e -v -m e2e

test-all:
	$(PYTEST) tests -v

lint:
	$(RUFF) check src tests

fmt:
	$(RUFF) format src tests

run:
	$(UVICORN) lightsync.dashboard.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
