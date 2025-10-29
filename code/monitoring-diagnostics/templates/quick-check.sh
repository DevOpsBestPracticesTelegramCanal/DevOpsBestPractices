#!/bin/bash
# Быстрая проверка стека мониторинга
echo "=== БЫСТРАЯ ДИАГНОСТИКА ==="

echo "1. Проверяем контейнеры:"
docker-compose ps

echo ""
echo "2. Проверяем Prometheus targets:"
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, lastError: .lastError}'

echo ""
echo "3. Проверяем demo-app метрики:"
curl -s http://localhost:8080/metrics | grep -c "http_requests_total"

echo ""
echo "4. Тестируем Prometheus запрос:"
curl -s "http://localhost:9090/api/v1/query?query=up" | jq '.data.result[] | {job: .metric.job, value: .value[1]}'

echo ""
echo "5. Проверяем Grafana datasource:"
curl -s -u admin:admin123 http://localhost:3000/api/datasources | jq '.[] | {name: .name, url: .url}'

echo ""
echo "=== РЕКОМЕНДАЦИИ ==="
echo "Если проблемы:"
echo "1. chmod +x fix-grafana-datasource.sh && ./fix-grafana-datasource.sh"
echo "2. chmod +x test-metrics.sh && ./test-metrics.sh"