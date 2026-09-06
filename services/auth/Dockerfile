FROM python:3.12-slim

# This matches your exact folder structure!
WORKDIR /SimplifyNextHackathon/services/auth

# Copy the requirements and install them
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the auth files (app, schema.sql, etc.)
COPY . .

# Expose port 8001
EXPOSE 8001