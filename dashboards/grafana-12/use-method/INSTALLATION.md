# 📥 Установка USE Method Dashboard

## Способ 1: Автоматическая установка (рекомендуется)

### Быстрая установка одной командой:
```bash
curl -s https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/scripts/install-use-method-dashboard.sh | bash -s -- http://localhost:3000 admin your_password
```

### Или скачайте и запустите скрипт:
```bash
wget https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/scripts/install-use-method-dashboard.sh
chmod +x install-use-method-dashboard.sh
./install-use-method-dashboard.sh http://localhost:3000 admin your_password
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
cat dashboards/grafana-12/use-method/use-method-working.json | clip.exe  # WSL
# или
cat dashboards/grafana-12/use-method/use-method-working.json | pbcopy     # macOS
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
  -d @dashboards/grafana-12/use-method/use-method-working.json \
  http://localhost:3000/api/dashboards/db
```

---

## ✅ Проверка установки

После установки дашборд доступен по адресу:
```
http://localhost:3000/d/use-method-complete
```

Вы увидите **4 разворачивающиеся секции**:
- 💻 **CPU - Processor** (3 panels)
- 🧠 **Memory - RAM** (3 panels)  
- 💾 **Disk I/O - Storage** (3 panels)
- 🌐 **Network - Interfaces** (3 panels)

---

## 📋 Требования

- **Grafana**: 12.x
- **Prometheus**: любая версия
- **Node Exporter**: установлен на мониторируемых хостах
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
✅ Collapsible rows работают  

---

## 📞 Поддержка

- **GitHub**: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
- **Telegram**: @DevOpsBestPractices
- **Issues**: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/issues
