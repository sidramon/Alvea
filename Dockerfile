FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# State directories must exist and be writable (overridden by volumes at runtime)
RUN mkdir -p workspace plan tasks runtime vision

EXPOSE 5000

CMD ["python", "main.py"]
