FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
WORKDIR /app
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/orchestrator/requirements.txt ./services/orchestrator/requirements.txt
RUN pip install --no-cache-dir . -r services/orchestrator/requirements.txt
COPY services/orchestrator ./services/orchestrator
WORKDIR /app/services
EXPOSE 8003
CMD ["uvicorn", "orchestrator.api:app", "--host", "0.0.0.0", "--port", "8003"]
