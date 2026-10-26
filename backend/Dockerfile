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

# Optional Gmail notices (ADR-024). Off by default so the image stays lean; set
# INSTALL_GMAIL=1 at build time to add the read-only Gmail client. The runtime lock is a
# constraints file here, so the validated base pins are never changed.
ARG INSTALL_GMAIL=0
COPY requirements.gmail.lock ./
RUN if [ "$INSTALL_GMAIL" = "1" ]; then \
        python -m pip install \
            --no-cache-dir --retries 8 --timeout 60 \
            -c requirements.runtime.lock -r requirements.gmail.lock; \
    fi

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN addgroup --system app && adduser --system --ingroup app app
RUN chown -R app:app /app

EXPOSE 8000
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
