# Four Golden Signals — Материалы для Telegram канала

## 📋 Описание

Материалы для публикации в Telegram канале "DevOps-best-practices" по теме **Four Golden Signals** от Google SRE.

## 📁 Структура материалов

```
articles/telegram/four-golden-signals/
├── README.md           # Описание (этот файл)
├── telegram-post.md    # Готовый пост для Telegram (684 символа)
└── prometheus-queries.md # Примеры Prometheus запросов

code/four-golden-signals/
├── demo-queries.promql    # PromQL запросы для демонстрации
└── quick-start.sh        # Скрипт быстрого запуска

examples/four-golden-signals/
└── grafana-examples.md   # Примеры использования в Grafana
```

## 🎯 Four Golden Signals

**Методология мониторинга от Google SRE:**

1. **📊 Latency** — время отклика на запросы
2. **🚀 Traffic** — объем нагрузки на систему  
3. **❌ Errors** — частота ошибок
4. **🔄 Saturation** — насыщенность ресурсов

## 📱 Telegram пост

**Файл**: `telegram-post.md`  
**Размер**: 684 символа (< 800 как требуется)

Готов к публикации в канале @DevOps_best_practices

## 🔗 Связанные материалы

**В этом репозитории:**
- [Grafana Dashboard](../../../dashboards/grafana-12/four-golden-signals/) — готовый дашборд
- [Docker Compose стек](../../../code/monitoring-diagnostics/templates/) — полная среда мониторинга
- [Demo приложение](../../../code/monitoring-diagnostics/templates/app-simulator/) — генератор метрик

## ⚡ Быстрый старт

```bash
# Клонируем репозиторий
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
cd DevOpsBestPractices

# Запускаем готовый стек мониторинга
cd code/monitoring-diagnostics/templates
docker-compose up -d

# Открываем Grafana
# http://localhost:3000 (admin/admin123)
```

## 📊 Что включено

- ✅ Prometheus для сбора метрик Four Golden Signals
- ✅ Grafana с готовыми дашбордами
- ✅ Demo-приложение с реалистичными метриками
- ✅ Node Exporter для системных метрик
- ✅ Alertmanager для уведомлений

## 📝 Автор

**DevOps-best-practices Team**  
**Telegram канал**: @DevOps_best_practices  
**GitHub**: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices