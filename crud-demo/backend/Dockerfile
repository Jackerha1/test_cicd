FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .

ENV FLASK_APP=app:create_app

EXPOSE 5000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
