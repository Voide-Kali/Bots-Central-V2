FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.runtime.lock ./
RUN python -m pip install \
    --no-cache-dir \
    --retries 8 \
    --timeout 60 \
    -r requirements.runtime.lock

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN addgroup --system app && adduser --system --ingroup app app
RUN chown -R app:app /app

EXPOSE 8000
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
