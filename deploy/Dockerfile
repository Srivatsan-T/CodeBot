# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install uv

# Copy only the dependency files first to cache them
COPY pyproject.toml .
# If you had a uv.lock, you'd copy it here too

# Install dependencies using uv
# --system flag installs into the system python environment (no venv needed in docker)
# We specify the PyTorch CPU index to avoid downloading massive CUDA packages that exhaust EC2 disk space
RUN uv pip install --system --no-cache --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match -r pyproject.toml

# Copy the rest of the application
COPY src/ src/
# Expose ports
# Streamlit
EXPOSE 8501
# Webhook Server
EXPOSE 8000

# Default command (overridden in docker-compose)
CMD ["uv", "run", "streamlit", "run", "src/app.py"]
