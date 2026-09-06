FROM python:3.12-slim

WORKDIR /SimplifyNextHackathon/services/feedback

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002