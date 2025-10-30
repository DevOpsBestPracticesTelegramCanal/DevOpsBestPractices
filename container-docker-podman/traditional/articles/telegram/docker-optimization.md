# 🐳 Docker Оптимизация 

## 🚀 Базовые правила

**Multi-stage builds** - уменьшают размер образа на 80%:

```dockerfile
FROM node:18 AS builder
COPY package*.json ./
RUN npm ci --production

FROM node:18-alpine
COPY --from=builder /app/node_modules ./
CMD ["npm", "start"]
```

## 📦 .dockerignore

Обязательно исключайте:
- `node_modules/`
- `.git/`
- `*.log`
- `Dockerfile`

## ⚡ Кэширование слоёв

Правильный порядок команд:
1. `COPY package*.json` (меняется редко)
2. `RUN npm install`
3. `COPY src/` (меняется часто)

## 🔒 Безопасность

```dockerfile
# Не root пользователь
USER node
# Read-only filesystem
RUN chmod -R 755 /app
```

**Результат**: образы <100MB, сборка <30сек, безопасность ++

💡 **Совет**: используйте `dive` для анализа слоёв образа

📖 Подробнее: [DevOpsBestPractices/container-docker-podman](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/tree/main/container-docker-podman)