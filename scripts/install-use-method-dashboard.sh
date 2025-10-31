#!/bin/bash

# Автоматическая установка USE Method Dashboard в Grafana 12
# Использование: ./install-use-method-dashboard.sh <grafana_url> <username> <password>

set -e

GRAFANA_URL="${1:-http://localhost:3000}"
GRAFANA_USER="${2:-admin}"
GRAFANA_PASS="${3:-admin}"

echo "🚀 Установка USE Method Dashboard..."
echo "📍 Grafana: ${GRAFANA_URL}"

# Клонирование репозитория во временную директорию
TEMP_DIR=$(mktemp -d)
cd "${TEMP_DIR}"

echo "📥 Клонирование репозитория..."
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git

# Импорт дашборда
echo "📊 Импорт дашборда..."
DASHBOARD_FILE="DevOpsBestPractices/dashboards/grafana-12/use-method/use-method-working.json"

curl -X POST \
  -H "Content-Type: application/json" \
  -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  -d @"${DASHBOARD_FILE}" \
  "${GRAFANA_URL}/api/dashboards/db"

echo ""
echo "✅ Установка завершена!"
echo "🌐 Дашборд доступен: ${GRAFANA_URL}/d/use-method-complete"
echo ""
echo "📋 Секции дашборда:"
echo "  💻 CPU - Processor (3 panels)"
echo "  🧠 Memory - RAM (3 panels)"
echo "  💾 Disk I/O - Storage (3 panels)"
echo "  🌐 Network - Interfaces (3 panels)"

# Очистка
cd ~
rm -rf "${TEMP_DIR}"
