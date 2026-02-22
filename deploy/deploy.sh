#!/bin/bash
set -e

echo "Starting deployment..."

# 1. Safely pull latest changes from git
echo "Saving any local changes..."
git stash push -u -m "Auto-stash before deploy" || true

echo "Pulling latest master..."
git pull

echo "Restoring local changes (if any)..."
git stash pop || true

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
