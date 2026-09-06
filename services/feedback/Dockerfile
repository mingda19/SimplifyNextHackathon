FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
WORKDIR /app
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/feedback/requirements.txt ./services/feedback/requirements.txt
RUN pip install --no-cache-dir . -r services/feedback/requirements.txt
COPY services/feedback ./services/feedback
WORKDIR /app/services/feedback
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
