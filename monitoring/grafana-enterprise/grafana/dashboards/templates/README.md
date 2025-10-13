# 📊 Grafana 12 Dashboard Templates

Коллекция готовых дашбордов для Grafana 12 Enterprise Edition из Telegram канала @devops_best_practices

## 📁 Доступные шаблоны

### 1. Grafana 12 Best Practices Demo ⭐
**Файл:** \grafana-12-best-practices.json\

**Включает 4 секции:**
- ✅ System Overview - статус системы, CPU, память
- ✅ Network Metrics - сетевой трафик, ошибки
- ✅ Disk & Storage - дисковые операции
- ✅ Advanced Metrics - load average, context switches

### 2. Node Exporter Full (ID: 1860) 🔥
**Файл:** \
ode-exporter-full.json\

**Самый популярный дашборд для мониторинга серверов!**
- ✅ 30+ панелей с метриками
- ✅ CPU, Memory, Network, Disk
- ✅ System Load, Processes
- ✅ Используется в 100,000+ установках

## 📥 Как импортировать дашборд

### Вариант 1: Через UI Grafana

1. Откройте Grafana: http://localhost:3000
2. Нажмите **+** (слева в меню) → **Import dashboard**
3. Нажмите **Upload JSON file**
4. Выберите файл шаблона
5. Выберите **Prometheus** как Data Source
6. Нажмите **Import**

### Вариант 2: Автоматическая загрузка ✨

Поместите JSON файл в папку:
\\\
./grafana/dashboards/
\\\

Grafana автоматически загрузит все дашборды при запуске!

## 🎨 Кастомизация

После импорта вы можете:
- Изменить временные интервалы
- Добавить свои панели
- Настроить алерты
- Экспортировать обратно

## 📚 Ссылки

- [Grafana Documentation](https://grafana.com/docs/grafana/latest/)
- [Node Exporter Full Dashboard](https://grafana.com/grafana/dashboards/1860)
- [Telegram канал](https://t.me/devops_best_practices)

#Grafana12 #Dashboards #DevOps #NodeExporter
