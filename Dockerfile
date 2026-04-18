FROM python:3.12-slim

WORKDIR /app

# System tools: curl + sqlite3 + Node.js 20 LTS (includes npm & npx)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        sqlite3 \
        git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# State directories must exist and be writable (overridden by volumes at runtime)
RUN mkdir -p workspace plan tasks runtime vision

EXPOSE 5000

CMD ["python", "main.py"]
