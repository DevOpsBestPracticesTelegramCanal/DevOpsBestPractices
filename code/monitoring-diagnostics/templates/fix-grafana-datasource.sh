#!/bin/bash
# Исправление проблем с Grafana datasource
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

echo "[FIX] Исправление проблем с Grafana datasource..."

# 1. Проверяем доступность Prometheus
echo "Проверяем Prometheus..."
if ! curl -s http://localhost:9090/-/healthy >/dev/null 2>&1; then
    echo "❌ Prometheus недоступен. Запускаем..."
    docker-compose restart prometheus
    sleep 10
fi

# 2. Проверяем доступность Grafana
echo "Проверяем Grafana..."
if ! curl -s http://localhost:3000/api/health >/dev/null 2>&1; then
    echo "❌ Grafana недоступен. Запускаем..."
    docker-compose restart grafana
    sleep 15
fi

# 3. Удаляем существующий datasource
echo "Удаляем существующий datasource..."
curl -s -X DELETE -u admin:admin123 http://localhost:3000/api/datasources/1 2>/dev/null || echo "Datasource не найден"

# 4. Создаем новый datasource
echo "Создаем новый Prometheus datasource..."
curl -X POST \
  http://localhost:3000/api/datasources \
  -H 'Content-Type: application/json' \
  -u admin:admin123 \
  -d '{
    "name": "Prometheus",
    "type": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy",
    "isDefault": true,
    "jsonData": {
      "httpMethod": "POST",
      "timeInterval": "15s"
    }
  }'

echo ""
echo "✅ Datasource создан"

# 5. Тестируем datasource
echo "Тестируем подключение..."
sleep 5

RESULT=$(curl -s -X POST \
  "http://localhost:3000/api/datasources/proxy/1/api/v1/query?query=up" \
  -H 'Content-Type: application/json' \
  -u admin:admin123)

if echo "$RESULT" | grep -q "success"; then
    echo "✅ Datasource работает корректно"
    echo "Доступные targets:"
    curl -s -X POST \
      "http://localhost:3000/api/datasources/proxy/1/api/v1/query?query=up" \
      -u admin:admin123 | jq -r '.data.result[].metric | "\(.job) - \(.instance)"' 2>/dev/null || echo "Parsing error"
else
    echo "❌ Проблемы с datasource"
    echo "Response: $RESULT"
fi

echo ""
echo "[INFO] Grafana доступен по адресу: http://localhost:3000"
echo "[INFO] Логин: admin, Пароль: admin123"