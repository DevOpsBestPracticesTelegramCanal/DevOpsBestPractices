# 📥 Установка Four Golden Signals Dashboard

## Способ 1: Автоматическая установка (рекомендуется)

### Быстрая установка одной командой:
```bash
curl -s https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/scripts/install-four-golden-signals-dashboard.sh | bash -s -- http://localhost:3000 admin your_password
```

### Или скачайте и запустите скрипт:
```bash
wget https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/scripts/install-four-golden-signals-dashboard.sh
chmod +x install-four-golden-signals-dashboard.sh
./install-four-golden-signals-dashboard.sh http://localhost:3000 admin your_password
```

---

## Способ 2: Ручная установка через UI

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git
cd DevOpsBestPractices
```

2. **Скопируйте JSON в буфер:**
```bash
cat dashboards/grafana-12/four-golden-signals/four-golden-signals-dashboard.json | clip.exe  # WSL
# или
cat dashboards/grafana-12/four-golden-signals/four-golden-signals-dashboard.json | pbcopy     # macOS
```

3. **Импортируйте в Grafana:**
   - Откройте Grafana: http://localhost:3000
   - Перейдите: **Dashboards → Import**
   - Вставьте JSON (Ctrl+V)
   - Нажмите **"Load"** → **"Import"**

---

## Способ 3: API импорт
```bash
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git
cd DevOpsBestPractices

curl -X POST \
  -H "Content-Type: application/json" \
  -u admin:your_password \
  -d @dashboards/grafana-12/four-golden-signals/four-golden-signals-dashboard.json \
  http://localhost:3000/api/dashboards/db
```

---

## ✅ Проверка установки

После установки дашборд доступен по адресу:
```
http://localhost:3000/d/four-golden-signals
```

Вы увидите **4 разворачивающиеся секции**:
- 📊 **Latency** (Response Time панели)
- 🚀 **Traffic** (Request Rate панели)  
- ❌ **Errors** (Error Rate панели)
- 🔄 **Saturation** (Resource Usage панели)

---

## 📋 Требования

- **Grafana**: 12.x
- **Prometheus**: любая версия
- **Demo App**: для генерации метрик Four Golden Signals
- **Datasource UID**: `prometheus` (настройте в Grafana)

---

## 🔧 Настройка Prometheus datasource

Если дашборд показывает "No data":

1. Перейдите: **Connections → Data sources**
2. Добавьте **Prometheus**:
   - Name: `Prometheus`
   - URL: `http://prometheus:9090`
   - **UID: `prometheus`** (важно!)
3. **Save & Test**

---

## 🧪 Протестировано

✅ Grafana 12.0.0  
✅ Ubuntu 22.04 / WSL2  
✅ Docker Compose  
✅ Four Golden Signals метрики  
✅ Demo App генерирует данные  

---

## 📞 Поддержка

- **GitHub**: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
- **Telegram**: @DevOps_best_practices
- **Issues**: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/issues