FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
# Логи пишем без буферизации, иначе они теряются при падении контейнера.
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY data /app/data
COPY tests /app/tests
COPY .coveragerc /app/.coveragerc

# Run as an unprivileged user: a remote-code-execution bug in the API must not
# hand over root inside the container. The catalog builder writes into /app/data,
# so the whole tree is owned by the service user.
RUN useradd --create-home --uid 10001 astroverse \
    && chown -R astroverse:astroverse /app
USER astroverse

WORKDIR /app/backend
EXPOSE 8000

ENTRYPOINT ["python", "/app/backend/entrypoint.py"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
