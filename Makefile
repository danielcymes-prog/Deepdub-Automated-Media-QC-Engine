.PHONY: install fmt fmt-check lint type test check schemas docker

install:
	uv sync

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

type:
	uv run mypy

test:
	uv run pytest -q

check: fmt-check lint type test

schemas:
	uv run python scripts/export_schemas.py

docker:
	docker build -t deepdub-qc:dev .
