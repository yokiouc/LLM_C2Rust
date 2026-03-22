FROM python:3.11-slim-bookworm

WORKDIR /app

RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get install -y --no-install-recommends make curl; \
    rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY Makefile /app/Makefile
COPY apps/api /app
COPY retrieval /app/retrieval

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
