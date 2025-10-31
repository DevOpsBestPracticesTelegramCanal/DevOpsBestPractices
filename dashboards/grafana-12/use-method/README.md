# USE Method Dashboard для Grafana 12

## 📊 Описание

Дашборд для мониторинга инфраструктуры по методу **USE (Utilization, Saturation, Errors)** от Брендана Грегга.

## 🎯 Метод USE

Для каждого ресурса проверяем:
- **Utilization** (Утилизация) - процент времени, когда ресурс занят
- **Saturation** (Насыщение) - очередь запросов к ресурсу
- **Errors** (Ошибки) - количество ошибок ресурса

## 🔧 Структура дашборда

Дашборд содержит 4 разворачивающиеся секции (collapsible rows):

### 💻 CPU - Processor (3 panels)
- **CPU Utilization** - загрузка процессора (%)
- **CPU Saturation (Load)** - Load Average
- **CPU Errors** - ошибки CPU

### 🧠 Memory - RAM (3 panels)
- **Memory Utilization** - использование оперативной памяти (%)
- **Memory Saturation (Swap)** - активность swap
- **Memory Errors** - поврежденная память

### 💾 Disk I/O - Storage (3 panels)
- **Disk Utilization** - загрузка дисков (%)
- **Disk Saturation (Queue)** - очередь дисковых операций
- **Disk Errors** - ошибки дисков

### 🌐 Network - Interfaces (3 panels)
- **Network Utilization** - использование сети (Mbps)
- **Network Saturation (Drops)** - потерянные пакеты
- **Network Errors** - ошибки сети

## 📥 Установка

1. Скопируйте JSON из файла `use-method-full.json`
2. В Grafana перейдите: **Dashboards → Import**
3. Вставьте JSON и нажмите **"Load"** → **"Import"**

## 📋 Требования

- **Grafana**: 12.x
- **Prometheus**: любая версия
- **Node Exporter**: установлен на мониторируемых хостах

## 🔗 Ссылки

- [USE Method by Brendan Gregg](http://www.brendangregg.com/usemethod.html)
- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Node Exporter](https://github.com/prometheus/node_exporter)

## 📝 Автор

DevOps Best Practices Telegram Channel
