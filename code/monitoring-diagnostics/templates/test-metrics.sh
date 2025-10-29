#!/bin/bash
# Тестирование метрик и генерация трафика
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

echo "[TEST] Тестирование метрик и генерация данных..."

# 1. Проверяем demo-app
echo "Проверяем demo-app..."
if ! curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo "❌ Demo-app недоступен. Запускаем..."
    docker-compose restart demo-app
    sleep 10
fi

# 2. Генерируем базовый трафик
echo "Генерируем тестовый трафик..."
for i in {1..20}; do
    # Успешные запросы
    curl -s http://localhost:8080/ >/dev/null &
    curl -s http://localhost:8080/health >/dev/null &
    curl -s http://localhost:8080/api/users >/dev/null &
    
    # Некоторые запросы с ошибками
    if [ $((i % 5)) -eq 0 ]; then
        curl -s http://localhost:8080/api/orders >/dev/null &
        curl -s http://localhost:8080/nonexistent >/dev/null &
    fi
    
    sleep 0.5
done

wait
echo "✅ Трафик сгенерирован"

# 3. Проверяем метрики
echo ""
echo "Проверяем созданные метрики..."
sleep 5

echo "--- HTTP Requests Total ---"
curl -s http://localhost:8080/metrics | grep "http_requests_total" | head -5

echo ""
echo "--- HTTP Request Duration ---"
curl -s http://localhost:8080/metrics | grep "http_request_duration_seconds" | head -3

# 4. Проверяем что Prometheus собирает метрики
echo ""
echo "Проверяем сбор метрик в Prometheus..."
sleep 5

QUERY="http_requests_total"
RESULT=$(curl -s "http://localhost:9090/api/v1/query?query=$QUERY")

if echo "$RESULT" | grep -q "success"; then
    echo "✅ Prometheus собирает метрики http_requests_total"
    echo "Количество серий:"
    echo "$RESULT" | jq '.data.result | length' 2>/dev/null || echo "Parsing error"
else
    echo "❌ Prometheus не собирает метрики"
    echo "Response: $RESULT"
fi

# 5. Проверяем метрики через Grafana
echo ""
echo "Проверяем метрики через Grafana datasource..."
GRAFANA_RESULT=$(curl -s -X POST \
  "http://localhost:3000/api/datasources/proxy/1/api/v1/query?query=http_requests_total" \
  -u admin:admin123)

if echo "$GRAFANA_RESULT" | grep -q "success"; then
    echo "✅ Grafana получает метрики через datasource"
else
    echo "❌ Grafana не получает метрики"
    echo "Response: $GRAFANA_RESULT"
fi

echo ""
echo "[INFO] Для проверки дашбордов:"
echo "1. Откройте http://localhost:3000"
echo "2. Логин: admin, Пароль: admin123"
echo "3. Перейдите в Four Golden Signals Dashboard"
echo "4. Убедитесь что переменная Job = demo-app"

echo ""
echo "Для генерации дополнительного трафика:"
echo "python app-simulator/load-generator.py --mode steady --rps 5 --duration 300"