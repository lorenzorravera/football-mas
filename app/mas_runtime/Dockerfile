FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy full project (db/ and agent_v3/ from repo root)
COPY . .

# Set Python path so db/ is importable
ENV PYTHONPATH=/app

WORKDIR /app/Ethan/agent_v3

# Expose Chainlit port
EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
