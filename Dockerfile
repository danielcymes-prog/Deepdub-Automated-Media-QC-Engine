# Canonical execution environment (ADR-008).
# Determinism policy: FFmpeg comes from the Debian bookworm repository of this
# base image. At release time, pin this image by digest and record the exact
# ffmpeg version; upgrading FFmpeg is a release event requiring a full
# golden-corpus re-run (see docs/RISKS.md R1).
FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version | head -1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY presets ./presets
COPY schemas ./schemas

RUN pip install --no-cache-dir .

ENTRYPOINT ["deepdub-qc"]
CMD ["--help"]
