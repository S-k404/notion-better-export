FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install the package (and its declared dependencies) from pyproject.toml
COPY pyproject.toml README.md LICENSE ./
COPY notion_better_export ./notion_better_export
RUN pip install --no-cache-dir .

# Run as an unprivileged user; exports are written to the mounted /vault volume
RUN useradd --create-home --uid 1000 nbe && mkdir /vault && chown nbe /vault
USER nbe

# `auto` mode (and any relative path) lands in the mounted volume, not the image
ENV EXPORT_OUT_DIR="/vault/Notion Better Export"
WORKDIR /vault

ENTRYPOINT ["notion-better-export"]
CMD ["--help"]
