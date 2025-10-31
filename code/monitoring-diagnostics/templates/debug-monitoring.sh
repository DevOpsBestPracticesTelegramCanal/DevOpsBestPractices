#!/bin/bash
# Диагностика проблем с мониторинг стеком
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

echo "=== DEBUGGING MONITORING STACK ==="
echo ""

# 1. Проверка запущенных контейнеров
echo "[CONTAINERS] Статус контейнеров:"
docker-compose ps
echo ""

# 2. Проверка сетевого подключения
echo "[NETWORK] Проверка портов:"
for port in 9090 3000 9093 9100 8080; do
    if netstat -tuln 2>/dev/null | grep -q ":$port "; then
        echo "✅ Порт $port: LISTEN"
    else
        echo "❌ Порт $port: NOT AVAILABLE"
    fi
done
echo ""

# 3. Проверка Prometheus targets
echo "[PROMETHEUS] Targets status:"
if curl -s http://localhost:9090/api/v1/targets 2>/dev/null | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}' 2>/dev/null; then
    echo "✅ Prometheus API доступен"
else
    echo "❌ Prometheus API недоступен"
fi
echo ""

# 4. Проверка метрик demo-app
echo "[DEMO-APP] Проверка метрик:"
if curl -s http://localhost:8080/metrics 2>/dev/null | grep -q "http_requests_total"; then
    echo "✅ Demo-app метрики доступны"
    echo "Примеры метрик:"
    curl -s http://localhost:8080/metrics | grep -E "(http_requests_total|http_request_duration)" | head -3
else
    echo "❌ Demo-app метрики недоступны"
fi
echo ""

# 5. Проверка Grafana datasource
echo "[GRAFANA] Проверка datasource:"
if curl -s -u admin:admin123 http://localhost:3000/api/datasources 2>/dev/null | jq '.[] | {name: .name, type: .type, url: .url}' 2>/dev/null; then
    echo "✅ Grafana datasources доступны"
else
    echo "❌ Grafana datasources недоступны"
fi
echo ""

# 6. Тест Prometheus запроса
echo "[QUERY] Тест Prometheus запроса:"
QUERY="up"
if curl -s "http://localhost:9090/api/v1/query?query=$QUERY" | jq '.data.result[] | {metric: .metric, value: .value[1]}' 2>/dev/null; then
    echo "✅ Prometheus запросы работают"
else
    echo "❌ Prometheus запросы не работают"
fi
echo ""

# 7. Логи контейнеров (последние 10 строк)
echo "[LOGS] Последние ошибки в логах:"
echo "--- Prometheus ---"
docker-compose logs --tail=5 prometheus | grep -i error || echo "Ошибок не найдено"
echo ""
echo "--- Grafana ---"
docker-compose logs --tail=5 grafana | grep -i error || echo "Ошибок не найдено"
echo ""
echo "--- Demo-app ---"
docker-compose logs --tail=5 demo-app | grep -i error || echo "Ошибок не найдено"
echo ""

# 8. Рекомендации по исправлению
echo "[RECOMMENDATIONS] Рекомендации:"
echo "1. Если контейнеры не запущены: docker-compose up -d"
echo "2. Если порты заняты: docker-compose down && docker-compose up -d"
echo "3. Если datasource недоступен: перезапустить Grafana: docker-compose restart grafana"
echo "4. Если demo-app не отвечает: docker-compose restart demo-app"
echo "5. Полная перезагрузка стека: docker-compose down -v && docker-compose up -d"
echo ""

echo "=== ДИАГНОСТИКА ЗАВЕРШЕНА ==="