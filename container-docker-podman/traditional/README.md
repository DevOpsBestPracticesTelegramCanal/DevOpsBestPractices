# 📦 Traditional Containers: Docker & Podman

Foundation knowledge for container technologies with practical examples and migration paths.

## 🎯 Content Overview

### Docker Fundamentals
- Container lifecycle management
- Image building best practices
- Network and storage patterns
- Multi-stage builds optimization

### Podman Advantages
- Rootless containers security
- Pod-based architecture
- systemd integration
- Docker compatibility layer

### Migration Strategies
- Docker to Podman transition
- Existing workload migration
- CI/CD pipeline adaptation
- Team training materials

## 📚 Structure

```
traditional/
├── articles/telegram/    # Quick tips (≤800 chars)
├── code/                # Practical examples
├── scripts/             # Automation tools
├── templates/           # Production templates
├── examples/            # Learning scenarios
├── tools/               # Helper utilities
└── documentation/       # Comprehensive guides
```

## 🚀 Quick Examples

### Docker Multi-stage Build
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

FROM node:18-alpine AS runtime
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
```

### Podman Systemd Service
```bash
# Generate systemd unit
podman generate systemd --new nginx > ~/.config/systemd/user/nginx.service

# Enable and start
systemctl --user enable nginx.service
systemctl --user start nginx.service
```

## 📋 Learning Path

1. **Container Basics** (1-2 weeks)
2. **Docker Mastery** (2-3 weeks)  
3. **Podman Migration** (1-2 weeks)
4. **Production Patterns** (2-3 weeks)

## 🎯 Success Criteria

- ✅ Build optimized images (<100MB)
- ✅ Implement rootless containers
- ✅ Automate with scripts
- ✅ Deploy production workloads