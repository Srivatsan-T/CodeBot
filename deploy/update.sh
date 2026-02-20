#!/bin/bash
# Script to update the application

set -e

echo "Pulling latest changes..."
git pull

echo "Rebuilding and restarting services..."
./deploy/start.sh
