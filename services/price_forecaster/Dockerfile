# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends libgomp1
WORKDIR /app
# pantry_common (fail-closed bearer auth, shared by every other service) --
# `pip install .` installs it as a real package, so it's importable
# regardless of this image's flat /app layout.
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/price_forecaster/requirements.txt ./requirements.txt
# xgboost --no-deps: see requirements.txt for why (an unconditional, unused
# 250MB+ nvidia-nccl CUDA dependency, and a pin that's confirmed compatible
# with the pretrained model rather than just "latest").
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install . -r requirements.txt && \
    pip install --no-deps xgboost==3.4.1
COPY services/price_forecaster ./
# forecast.py's SKU->commodity resolver reads the SELECTED map from here at
# runtime (see REPO_ROOT in forecast.py). Without this file present, every
# dspi_series lookup that isn't already an exact alias silently returns no
# forecast. ./data/ already exists in the image (train/val/test.csv) --
# this just adds one more file to it, no clash.
COPY data/dspi_features.py ./data/dspi_features.py
EXPOSE 8004
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
