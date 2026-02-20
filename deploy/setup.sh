#!/bin/bash
set -e

# Redirect output to log file
exec > >(tee -a /var/log/user-data.log) 2>&1

echo "Starting setup..."

# 1. Update System
sudo dnf update -y

# 2. Install Git (Already installed to clone this repo, but ensuring update)
sudo dnf install git -y

# 3. Install Docker
sudo dnf install docker -y
sudo service docker start
sudo systemctl enable docker

# 4. Add ec2-user to docker group
sudo usermod -a -G docker ec2-user

# 5. Install Docker Compose and Buildx plugins
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

ARCH=$(uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
sudo curl -SL https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-$ARCH -o /usr/local/lib/docker/cli-plugins/docker-buildx
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

# 6. Setup Swap (Optional but recommended for t2.micro/small instances)
if [ ! -f /swapfile ]; then
    echo "Setting up 2G swap file..."
    sudo dd if=/dev/zero of=/swapfile bs=128M count=16
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo "/swapfile swap swap defaults 0 0" | sudo tee -a /etc/fstab
fi

echo "Setup complete! Please logout and log back in to apply group changes."
