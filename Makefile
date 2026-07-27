.PHONY: install fmt fmt-check lint type test check layers schemas params docker docker-test pin-ffmpeg js-tests

# Canonical toolchain declaration (ADR-022). Sourced into docker build args so
# the pin lives in exactly one place.
include environment.lock

DOCKER_BUILD_ARGS = \
	--build-arg BASE_IMAGE=$(BASE_IMAGE) \
	--build-arg BASE_DIGEST=$(BASE_DIGEST) \
	--build-arg EXPECTED_FFMPEG_VERSION=$(EXPECTED_FFMPEG_VERSION)

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

layers:
	uv run --group lint lint-imports

test:
	uv run pytest -q

check: fmt-check lint type layers test

# Console client-side behaviour in jsdom (ADR-023). Deliberately NOT part of
# `check`: it needs a Node toolchain this Python project does not otherwise
# require. The pytest wrapper in tests/integration skips with an actionable
# reason when Node or jsdom is absent, so `check` stays green without it.
js-tests:
	npm install --prefix tests/js --no-audit --no-fund
	node tests/js/console.test.mjs

schemas:
	uv run python scripts/export_schemas.py

params:
	uv run python scripts/export_parameters.py

docker:
	docker build $(DOCKER_BUILD_ARGS) --target runtime -t deepdub-qc:dev .

# The canonical test run (ADR-022): full suite inside the pinned image, so the
# integration tests exercise the FFmpeg the product actually ships with.
docker-test:
	docker build $(DOCKER_BUILD_ARGS) --target test -t deepdub-qc:test .
	docker run --rm deepdub-qc:test

# Capture the FFmpeg version the pinned base image resolves to, for pasting
# into environment.lock. Run once on a machine with Docker; committing the
# value turns the build guard from "record" into "assert".
pin-ffmpeg:
	@docker build $(DOCKER_BUILD_ARGS) --target base -t deepdub-qc:base . >/dev/null
	@echo "Resolved FFmpeg in the pinned base image:"
	@docker run --rm --entrypoint cat deepdub-qc:base /opt/deepdub-qc/ffmpeg-version.txt
	@echo
	@echo "Set EXPECTED_FFMPEG_VERSION in environment.lock to the version token above."
