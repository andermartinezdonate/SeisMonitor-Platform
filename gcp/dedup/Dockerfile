FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY gcp/dedup/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared quake_stream package (parsers, models, dedup, geo, sources, region_priority)
COPY src/quake_stream/ /app/quake_stream/

# Copy the dedup service code
COPY gcp/dedup/main.py gcp/dedup/dedup_pipeline.py /app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "--timeout", "120", "main:app"]
