# Примеры использования Four Golden Signals в Grafana

## 📊 Готовые дашборды

В репозитории доступен готовый дашборд для Grafana 12:
- **Файл**: `/dashboards/grafana-12/four-golden-signals/four-golden-signals-dashboard.json`
- **Импорт**: Grafana → Dashboards → Import → Load JSON

## 🎯 Панели дашборда

### 1. Latency (Задержка)
- **Response Time p50** — медианное время ответа
- **Response Time p95** — 95-й процентиль
- **Response Time p99** — 99-й процентиль

### 2. Traffic (Трафик)  
- **Request Rate** — количество запросов в секунду
- **Traffic by Endpoint** — трафик по эндпоинтам
- **HTTP Methods** — распределение по методам

### 3. Errors (Ошибки)
- **Error Rate** — процент ошибок
- **4xx Errors** — клиентские ошибки  
- **5xx Errors** — серверные ошибки

### 4. Saturation (Насыщение)
- **CPU Usage** — загрузка процессора
- **Memory Usage** — использование памяти
- **Disk Usage** — загрузка дисков

## ⚡ Быстрый импорт

```bash
# 1. Запустить стек мониторинга
cd DevOpsBestPractices/code/monitoring-diagnostics/templates
docker-compose up -d

# 2. Открыть Grafana
# http://localhost:3000 (admin/admin123)

# 3. Импортировать дашборд
# Dashboards → Import → Upload JSON file
# Выбрать: dashboards/grafana-12/four-golden-signals/four-golden-signals-dashboard.json
```

## 🔧 Настройка переменных

Дашборд использует переменную `$job` для выбора приложения:
- **По умолчанию**: `demo-app`
- **Настройка**: Dashboard Settings → Variables → job

## 📈 Типичные значения

**Для demo-приложения:**
- **Latency**: p95 < 100ms
- **Traffic**: 10-50 RPS
- **Errors**: < 5%  
- **Saturation**: CPU < 50%, Memory < 70%

## 🚨 Рекомендуемые алерты

1. **High Latency**: p95 > 500ms
2. **High Error Rate**: > 5%
3. **High CPU**: > 80%
4. **Low Memory**: < 10% свободной

## 🔗 Связанные материалы

- [Prometheus запросы](../../articles/telegram/four-golden-signals/prometheus-queries.md)
- [Quick Start скрипт](../../code/four-golden-signals/quick-start.sh)
- [Demo приложение](../../code/monitoring-diagnostics/templates/app-simulator/)