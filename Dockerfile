# Use official Python base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv

# Copy project files needed for install
COPY pyproject.toml requirements.txt ./

# Pre-install dependencies (cached layer — only rebuilds when pyproject.toml changes)
RUN uv pip install --system -r requirements.txt

# Copy full application code
COPY . .

# Create runtime directories
RUN mkdir -p /app/logs /app/storage

# Install the project itself (registers console scripts like 'polymarket')
# Must run as root before switching to non-root user
RUN uv pip install --system -e .

# Create non-root user for security
RUN useradd -m -u 1000 polymarket && \
    chown -R polymarket:polymarket /app

# Switch to non-root user
USER polymarket

# Expose ports for API and Dashboard
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Run the bot
CMD ["polymarket"]
