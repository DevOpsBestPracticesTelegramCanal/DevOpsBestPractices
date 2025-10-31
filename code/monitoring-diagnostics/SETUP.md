# Мониторинг стек - Инструкция по настройке

## Быстрый старт

### 1. Развертывание стека

```bash
# Клонируем репозиторий
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git
cd DevOpsBestPractices/code/monitoring-diagnostics/templates

# Запускаем стек
docker-compose up -d
```

### 2. Доступ к сервисам

| Сервис | URL | Порт | Логин/Пароль |
|--------|-----|------|--------------|
| **Prometheus** | http://localhost:9090 | 9090 | - |
| **Grafana** | http://localhost:3000 | 3000 | admin/admin123 |
| **Alertmanager** | http://localhost:9093 | 9093 | - |
| **Node Exporter** | http://localhost:9100 | 9100 | - |
| **Blackbox Exporter** | http://localhost:9115 | 9115 | - |
| **Demo App** | http://localhost:8080 | 8080 | - |

### 3. Автоматическая настройка

**✅ Что настроено автоматически:**

- **Prometheus** на порту 9090 со всеми source конфигурациями
- **Grafana** с предустановленным Prometheus datasource
- **Дашборды** автоматически загружены из репозитория
- **Алерты** настроены для основных метрик

## Конфигурация источников данных

### Prometheus Configuration (порт 9090)

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
  
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
  
  - job_name: 'grafana'
    static_configs:
      - targets: ['grafana:3000']
```

### Grafana Datasource (автоматически)

```yaml
# grafana/provisioning/datasources/prometheus.yml
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
```

## Доступные дашборды

### 1. Four Golden Signals Dashboard
**Импорт:** Автоматически загружен  
**Путь:** `/var/lib/grafana/dashboards/four-golden-signals/`
- Latency (задержка)
- Traffic (трафик) 
- Errors (ошибки)
- Saturation (насыщенность)

### 2. USE Method Dashboard  
**Импорт:** Автоматически загружен
**Путь:** `/var/lib/grafana/dashboards/use-method/`
- Utilization (использование)
- Saturation (насыщенность)
- Errors (ошибки)

## Проверка работоспособности

### Быстрая проверка
```bash
# Статус контейнеров
docker-compose ps

# Проверка портов
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3000/api/health # Grafana  
curl http://localhost:9093/-/healthy  # Alertmanager
```

### Подробная диагностика
```bash
# Запуск диагностического скрипта
chmod +x ../../scripts/mega-diagnostic.sh
../../scripts/mega-diagnostic.sh

# Python анализатор
python3 ../../scripts/monitoring-analyzer.py
```

## Настройка алертов

### Email уведомления
Отредактируйте `alertmanager.yml`:
```yaml
global:
  smtp_smarthost: 'your-smtp:587'
  smtp_from: 'alerts@yourcompany.com'

receivers:
  - name: 'email-alerts'
    email_configs:
      - to: 'admin@yourcompany.com'
```

### Slack уведомления
```yaml
receivers:
  - name: 'slack-alerts'
    slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK_URL'
        channel: '#alerts'
```

## Troubleshooting

### Проблема: Порты заняты
```bash
# Проверка занятых портов
ss -tuln | grep -E ':(9090|3000|9093|9100)'

# Освобождение портов
sudo kill $(lsof -t -i:9090)
```

### Проблема: Недостаток памяти
```bash
# Проверка памяти
free -h

# Увеличение swap (если нужно)
sudo fallocate -l 2G /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Проблема: Docker volumes
```bash
# Очистка старых volumes
docker volume prune

# Пересоздание volumes
docker-compose down -v
docker-compose up -d
```

## Кастомизация

### Добавление новых targets
Отредактируйте `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'my-app'
    static_configs:
      - targets: ['app:8080']
```

### Импорт дополнительных дашбордов
```bash
# Скопировать в папку dashboards
cp my-dashboard.json ../../../dashboards/grafana-12/custom/

# Перезапустить Grafana
docker-compose restart grafana
```

## Полезные команды

```bash
# Логи сервисов
docker-compose logs prometheus
docker-compose logs grafana
docker-compose logs alertmanager

# Обновление конфигурации без перезапуска
curl -X POST http://localhost:9090/-/reload

# Остановка стека
docker-compose down

# Полная очистка (с данными)
docker-compose down -v
```

---

**GitHub:** https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices  
**Telegram:** @DevOps_best_practices