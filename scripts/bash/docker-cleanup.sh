#!/bin/bash
# Docker Cleanup Script
# Removes unused containers, images, and volumes

echo "🧹 Starting Docker cleanup..."

# Remove stopped containers
docker container prune -f

# Remove unused images
docker image prune -a -f

# Remove unused volumes
docker volume prune -f

# Remove unused networks
docker network prune -f

echo "✅ Docker cleanup completed!"
