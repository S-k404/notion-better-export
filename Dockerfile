FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir notion-client pyyaml rich

COPY . /app

ENTRYPOINT ["python3", "-m", "notion_better_export.cli"]
CMD ["--help"]
