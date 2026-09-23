FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY data /app/data
COPY tests /app/tests

WORKDIR /app/backend
EXPOSE 8000

ENTRYPOINT ["python", "/app/backend/entrypoint.py"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
