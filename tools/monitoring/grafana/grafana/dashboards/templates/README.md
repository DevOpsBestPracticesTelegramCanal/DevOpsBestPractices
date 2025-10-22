# 📊 Grafana 12 Dashboard Templates

Коллекция готовых дашбордов для Grafana 12 Enterprise Edition из Telegram канала @devops_best_practices

## 📁 Доступные шаблоны (3 дашборда)

### 1. Grafana 12 Features Showcase 🆕✨
**Файл:** \grafana-12-features-showcase.json\

**Демонстрирует новые фичи Grafana 12:**
- ✅ **Dashboard Tabs** - организация панелей во вкладки
- ✅ **Dashboard Outline** - древовидная навигация
- ✅ **Conditional Rendering** - динамическое отображение
- ✅ **Enhanced Tooltips** - улучшенные подсказки
- ✅ System, Network, Disk метрики

### 2. Node Exporter Full (ID: 1860) 🔥
**Файл:** \
ode-exporter-full.json\

**Самый популярный дашборд для мониторинга серверов!**
- ✅ 30+ панелей с метриками
- ✅ CPU, Memory, Network, Disk
- ✅ System Load, Processes
- ✅ Используется в 100,000+ установках

### 3. Grafana 12 Best Practices Demo ⭐
**Файл:** \grafana-12-best-practices.json\

**Простой дашборд для быстрого старта:**
- ✅ System Overview - статус, CPU, память
- ✅ Network Metrics - трафик, ошибки
- ✅ Disk & Storage - операции I/O
- ✅ Advanced Metrics - load average

## 📥 Как импортировать дашборд

### Вариант 1: Через UI Grafana

1. Откройте Grafana: http://localhost:3000
2. Нажмите **+** → **Import dashboard**
3. Нажмите **Upload JSON file**
4. Выберите файл шаблона
5. Выберите **Prometheus** как Data Source
6. Нажмите **Import**

### Вариант 2: Автоматическая загрузка ✨

Скопируйте JSON файлы в папку:
\\\ash
./grafana/dashboards/
\\\

Grafana автоматически загрузит все дашборды при запуске!

### Вариант 3: Прямая ссылка

\\\ash
# Grafana 12 Features Showcase
curl -o grafana-12-features.json https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/monitoring/grafana-enterprise/grafana/dashboards/templates/grafana-12-features-showcase.json

# Node Exporter Full
curl -o node-exporter.json https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/monitoring/grafana-enterprise/grafana/dashboards/templates/node-exporter-full.json

# Best Practices Demo
curl -o best-practices.json https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/monitoring/grafana-enterprise/grafana/dashboards/templates/grafana-12-best-practices.json
\\\

## 🎨 Кастомизация

После импорта вы можете:
- Изменить временные интервалы
- Добавить свои панели
- Настроить алерты
- Экспортировать обратно

## 📚 Ссылки

- [Grafana 12 Documentation](https://grafana.com/docs/grafana/latest/)
- [Node Exporter Full Dashboard](https://grafana.com/grafana/dashboards/1860)
- [Prometheus Queries](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Telegram канал](https://t.me/devops_best_practices)

#Grafana12 #Dashboards #DevOps #NodeExporter #BestPractices
