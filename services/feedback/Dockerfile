# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
WORKDIR /app
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/feedback/requirements.txt ./services/feedback/requirements.txt
# The sentiment second-opinion model (app/extract.py) is real inference on a
# CPU-only container -- pull torch's CPU wheel instead of letting pip resolve
# the default (CUDA-enabled on x86_64, several hundred MB to a few GB extra)
# build it will never use. Keep this version in sync with the torch==
# pin in requirements.txt: pip sees that exact version already satisfied
# and skips reinstalling it there.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu && \
    pip install . -r services/feedback/requirements.txt
COPY services/feedback ./services/feedback
WORKDIR /app/services/feedback
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
