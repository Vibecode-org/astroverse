FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
# Explicit runtime inputs: catalog fixtures and tests never enter this image.
COPY data/*.py /app/data/
COPY data/catalog_config.json /app/data/catalog_config.json
COPY data/ephemeris/de440s.bsp /app/data/ephemeris/de440s.bsp
COPY data/bootstrap/catalog.sqlite data/bootstrap/catalog.sqlite.manifest.json data/bootstrap/catalog.sqlite.sha256 data/bootstrap/release.json /app/data/bootstrap/
# Verify the delivered publication, independently of its former JSON source.
RUN python -m data.bootstrap_catalog verify /app/data/bootstrap/catalog.sqlite \
    && mkdir -p /app/data/runtime \
    && useradd --create-home --uid 10001 astroverse \
    && chown astroverse:astroverse /app/data/runtime
USER astroverse

WORKDIR /app/backend
EXPOSE 8000

ENTRYPOINT ["python", "/app/backend/entrypoint.py"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
