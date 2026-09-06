FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services
WORKDIR /app
COPY pyproject.toml ./
COPY services/pantry_common ./services/pantry_common
COPY services/auth/requirements.txt ./services/auth/requirements.txt
RUN pip install --no-cache-dir . -r services/auth/requirements.txt
COPY services/auth ./services/auth
WORKDIR /app/services/auth
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
