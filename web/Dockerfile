FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md /app/
COPY python /app/python

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["bm-gateway", "web", "serve", "--snapshot-file", "/data/runtime/latest_snapshot.json", "--host", "0.0.0.0", "--port", "8080"]
