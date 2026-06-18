# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Системные сертификаты для urllib (используется build_ca_bundle.py на этом же шаге)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docker/build_ca_bundle.py .
RUN python build_ca_bundle.py ca_bundle.pem

COPY tinvest_sync/ tinvest_sync/
COPY sync.py .

ENTRYPOINT ["python", "sync.py"]
CMD ["--from-last"]
