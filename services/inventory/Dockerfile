# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
WORKDIR /app
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/inventory/requirements.txt ./services/inventory/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install . -r services/inventory/requirements.txt
COPY services/inventory ./services/inventory
WORKDIR /app/services/inventory
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
