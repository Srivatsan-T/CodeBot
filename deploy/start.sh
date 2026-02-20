#!/bin/bash
# Script to build and start the application

set -e

if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one from .env.example or your local setup."
    exit 1
fi

echo "Building and starting services..."
docker compose up -d --build

echo "Services started. Logs:"
docker compose logs -f
