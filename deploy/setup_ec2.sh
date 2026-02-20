#!/bin/bash
# Setup script for Amazon Linux 2023

set -e # Exit on error

# Update system
echo "Updating system..."
sudo dnf update -y

# Install git
echo "Installing Git..."
sudo dnf install git -y

# Install Docker
echo "Installing Docker..."
sudo dnf install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user

# Install Docker Compose (v2 is a plugin now)
echo "Installing Docker Compose..."
sudo dnf install docker-compose-plugin -y

echo "Setup complete! Please log out and log back in for docker group compliance."
