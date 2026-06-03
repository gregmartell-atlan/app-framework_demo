# Atlan GitHub App Framework v3 connector
# Base image provides Python 3.11 + app-runtime dependencies

FROM registry.atlan.com/public/app-runtime-base:3

# Set app module (required by SDK)
ENV ATLAN_APP_MODULE=app.connector:GitHubConnector

# Install git for wiki cloning
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy application code
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app/ ./app/
COPY contract/ ./contract/

# Install Python dependencies
RUN uv sync --frozen --no-dev

# DO NOT override CMD/ENTRYPOINT — base image handles app startup
