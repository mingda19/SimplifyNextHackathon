FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/price_forecaster/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/price_forecaster ./
# forecast.py's SKU->commodity resolver reads the SELECTED map from here at
# runtime (see REPO_ROOT in forecast.py). Without this file present, every
# dspi_series lookup that isn't already an exact alias silently returns no
# forecast. ./data/ already exists in the image (train/val/test.csv) --
# this just adds one more file to it, no clash.
COPY data/dspi_features.py ./data/dspi_features.py
EXPOSE 8004
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004"]
