#!/bin/bash
# Four Golden Signals - Quick Start Script
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

set -e

echo "🎯 Four Golden Signals - Быстрый старт"
echo "======================================"

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker не установлен"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "[ERROR] Docker Compose не установлен"
    exit 1
fi

echo "[OK] Docker и Docker Compose установлены"

# Переход в директорию с мониторингом
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$SCRIPT_DIR/../monitoring-diagnostics/templates"

if [ ! -d "$MONITORING_DIR" ]; then
    echo "[ERROR] Директория мониторинга не найдена: $MONITORING_DIR"
    exit 1
fi

cd "$MONITORING_DIR"
echo "[OK] Переход в директорию: $MONITORING_DIR"

# Запуск стека мониторинга
echo "🚀 Запуск стека мониторинга..."
docker-compose up -d

# Ожидание запуска сервисов
echo "⏳ Ожидание запуска сервисов (30 секунд)..."
sleep 30

# Проверка сервисов
echo "🔍 Проверка сервисов..."

services=("prometheus:9090" "grafana:3000" "demo-app:8080")
for service in "${services[@]}"; do
    host_port="${service/:/:\/\/localhost:}"
    if curl -s "http://localhost:${service#*:}" > /dev/null; then
        echo "[OK] $service работает"
    else
        echo "[WARNING] $service недоступен"
    fi
done

echo ""
echo "✅ Стек мониторинга запущен!"
echo ""
echo "🔗 Ссылки:"
echo "   Grafana:    http://localhost:3000 (admin/admin123)"
echo "   Prometheus: http://localhost:9090"
echo "   Demo App:   http://localhost:8080"
echo ""
echo "📊 Four Golden Signals доступны в дашборде Grafana"
echo ""
echo "🛠️ Полезные команды:"
echo "   docker-compose logs    # логи сервисов"
echo "   docker-compose down    # остановка"
echo "   docker-compose ps      # статус контейнеров"
echo ""
echo "📝 Документация: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices"