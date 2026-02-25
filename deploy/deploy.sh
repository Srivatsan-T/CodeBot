#!/bin/bash
set -e

echo "Starting deployment..."

# 1. Safely pull latest changes from git
echo "Discarding local changes to tracked files to ensure successful pull..."
git reset --hard HEAD
git clean -fd

echo "Pulling latest master..."
git pull

# 2. Build and start containers
# Ensure an empty .env file exists so docker doesn't mount it as a directory
touch .env
# --build: Build images before starting containers.
# -d: Detached mode: Run containers in the background
# -f: Specify the location of the docker-compose file
docker compose -f deploy/docker-compose.yml up --build -d

# 3. Prune unused images to save space
docker image prune -f

echo "Deployment complete! Services are running."
