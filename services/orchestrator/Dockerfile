FROM python:3.12-slim

# 1. We set the workdir one level higher (in the services folder)
WORKDIR /SimplifyNextHackathon/services

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. We copy the code INTO a folder named 'orchestrator'
COPY . ./orchestrator/

EXPOSE 8003