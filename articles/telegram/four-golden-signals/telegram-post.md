# Four Golden Signals Dashboard для Grafana 12

## 📊 Описание

Дашборд для мониторинга приложений по методу **Four Golden Signals** от Google SRE.

## 🎯 Метод Four Golden Signals

Для каждого сервиса проверяем:
- **Latency** - время отклика
- **Traffic** - нагрузка (RPS)
- **Errors** - частота ошибок
- **Saturation** - загруженность ресурсов

## 📥 Установка

1. Скопируйте JSON из `four-golden-signals-dashboard.json`
2. Grafana: **Dashboards → Import**
3. Вставьте JSON → **Import**

## 📋 Требования

- **Grafana**: 12.x
- **Prometheus**: любая версия

## 📝 Автор

DevOps Best Practices