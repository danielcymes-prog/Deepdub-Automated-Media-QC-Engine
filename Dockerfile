# Canonical execution environment (ADR-008, ADR-022).
#
# Determinism policy: the base image is pinned by digest and the FFmpeg version
# is asserted at build time against environment.lock. Upgrading FFmpeg is a
# release event requiring a full golden-corpus re-run (docs/RISKS.md R1) —
# it must never happen as a side effect of rebuilding.
#
# Stages:
#   base    — pinned OS + Python + FFmpeg + WeasyPrint native libs
#   test    — base + dev dependencies + tests; the canonical test environment
#   runtime — base + the installed package only (default build target)
#
# Build via `make docker` / `make docker-test`, which pass the args from
# environment.lock — the single declaration of the pins. There are deliberately
# no defaults here: a plain `docker build .` fails at FROM rather than quietly
# building from a second, driftable copy of the digest.
ARG BASE_IMAGE
ARG BASE_DIGEST

FROM ${BASE_IMAGE}@${BASE_DIGEST} AS base

# Expected FFmpeg version, asserted below. Empty = record only, do not assert.
ARG EXPECTED_FFMPEG_VERSION=""

# ffmpeg: media analysis (pin policy above).
# libpango/libharfbuzz: WeasyPrint PDF rendering (ADR-007).
#
# The version is not pinned via apt because Debian removes superseded versions
# from the mirror on security updates, which would turn drift into an
# undiagnosable build failure at an arbitrary date (ADR-022 alternative (a)).
# Instead the resolved version is recorded and asserted, so drift is visible
# and attributable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/deepdub-qc \
    && ffmpeg -version | head -1 | tee /opt/deepdub-qc/ffmpeg-version.txt \
    && if [ -n "${EXPECTED_FFMPEG_VERSION}" ]; then \
           if ! grep -qF "${EXPECTED_FFMPEG_VERSION}" /opt/deepdub-qc/ffmpeg-version.txt; then \
               echo "ERROR: FFmpeg version mismatch (determinism guard, ADR-008/ADR-022)." >&2; \
               echo "  expected substring: ${EXPECTED_FFMPEG_VERSION}" >&2; \
               echo "  installed:          $(cat /opt/deepdub-qc/ffmpeg-version.txt)" >&2; \
               echo "  If this upgrade is intended, update environment.lock, re-run the" >&2; \
               echo "  golden corpus, and add a docs/VALIDATION.md entry (docs/RISKS.md R1)." >&2; \
               exit 1; \
           fi; \
           echo "FFmpeg version guard: OK (${EXPECTED_FFMPEG_VERSION})"; \
       else \
           echo "FFmpeg version guard: NOT SET — see environment.lock"; \
       fi

WORKDIR /app


# --- Canonical test environment (ADR-022) -----------------------------------
# The full suite runs here, so the integration tests exercise the same pinned
# FFmpeg the product ships with. Nothing may skip for a missing tool.
FROM base AS test

COPY --from=ghcr.io/astral-sh/uv:0.8.11 /uv /usr/local/bin/uv

# Node + npm for the console behaviour suite (ADR-023). This stage forbids
# skips (DEEPDUB_QC_REQUIRE_TOOLCHAIN=1 below), so every toolchain a suite
# needs must exist here; without Node the jsdom wrapper fails the run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    DEEPDUB_QC_REQUIRE_TOOLCHAIN=1

COPY pyproject.toml uv.lock README.md environment.lock ./
COPY src ./src
RUN uv sync --frozen --dev --python /usr/local/bin/python3

COPY presets ./presets
COPY schemas ./schemas
COPY scripts ./scripts
# config/ is test input: the Windows deployment installer round-trips
# server.example.yaml through ANSI encoding, so a test pins it to ASCII.
COPY config ./config
# assets/ is test input: the desktop-shortcut test verifies the shipped
# .ico exists and is a real ICO.
COPY assets ./assets
# docs/ is test input: the export drift tests compare the committed
# docs/parameter-catalogue.md byte-for-byte against a fresh render.
COPY docs ./docs
COPY tests ./tests
RUN npm install --prefix tests/js --no-audit --no-fund

# -rs surfaces any remaining skip in the log: in this image, a skipped
# integration test means the pinned toolchain is not what we think it is.
CMD ["uv", "run", "--no-sync", "pytest", "-q", "-rs"]


# --- Shipped runtime image (default target) ---------------------------------
FROM base AS runtime

COPY pyproject.toml README.md environment.lock ./
COPY src ./src
COPY presets ./presets
COPY schemas ./schemas

RUN pip install --no-cache-dir .

ENTRYPOINT ["deepdub-qc"]
CMD ["--help"]
