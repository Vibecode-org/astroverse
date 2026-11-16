# Test-only image. Retained JSON/numeric fixtures and provider modules belong
# here; its separate tag cannot replace the production runtime image.
FROM python:3.12-slim AS test
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend /app/backend
COPY data /app/data
COPY tests /app/tests
COPY .coveragerc /app/.coveragerc
RUN python -m data.bootstrap_catalog verify /app/data/bootstrap/catalog.sqlite \
    && mkdir -p /app/data/runtime \
    && useradd --create-home --uid 10001 astroverse \
    && chown -R astroverse:astroverse /app
USER astroverse
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["python", "/app/backend/entrypoint.py"]
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
