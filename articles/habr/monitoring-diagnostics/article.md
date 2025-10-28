# Комплексная диагностика инфраструктуры перед развертыванием системы мониторинга: практическое руководство

**TL;DR**: Методология полной диагностики среды перед установкой Prometheus и Grafana. Готовые bash-скрипты, Python-анализатор, интеграция с CI/CD. Позволяет предотвратить типичные ошибки развертывания мониторинга. Все инструменты протестированы в production.

## Введение: Цена ошибки

В production-окружении Prometheus перестал собирать метрики через 3 дня после установки. Причина — исчерпание лимита файловых дескрипторов (системный лимит по умолчанию 1024, Prometheus требует ≥65536). Восстановление заняло 8 часов, потеря данных — 72 часа метрик. Эту ситуацию можно было предотвратить предварительной диагностикой системных лимитов.

**Технические причины отказов при развертывании мониторинга:**

**1. Системные лимиты:**
- Лимит файловых дескрипторов (ulimit -n) по умолчанию 1024, Prometheus требует ≥65536
- Недостаток памяти: минимум 2GB для базового стека Prometheus+Grafana

**2. Конфликты ресурсов:**
- Занятые порты 9090 (Prometheus), 3000 (Grafana), 9093 (Alertmanager)
- Существующие Docker volumes с данными предыдущих установок

**3. Сетевые ограничения:**
- Firewall блокирует межсервисное взаимодействие
- DNS resolution для service discovery

<cut />

## Часть 1: Экспресс-диагностика системы

### Скрипт системной диагностики

Вместо десятков отдельных команд — единый скрипт, который проверяет всё необходимое:

**[Скачать diagnostic.sh](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/scripts/mega-diagnostic.sh)**

```bash
#!/bin/bash
# diagnostic.sh - Полная диагностика за один запуск
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

echo "=== SYSTEM DIAGNOSTIC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee diagnostic.log

# 1. Ресурсы
AVAILABLE_MEM=$(free -g | awk 'NR==2 {print $7}')
ROOT_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
CPU_CORES=$(nproc)
LOAD_AVG=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//')

echo "[Resources]"
echo "Memory: ${AVAILABLE_MEM}GB available $([ $AVAILABLE_MEM -ge 2 ] && echo OK || echo WARNING)"
echo "Disk: ${ROOT_USAGE}% used $([ $ROOT_USAGE -lt 85 ] && echo OK || echo WARNING)"  
echo "CPU: ${CPU_CORES} cores, Load: ${LOAD_AVG}"

# 2. Критические порты
echo -e "\n[Port Check]"
for port in 9090 3000 9093; do
    SERVICE_MAP=(9090:Prometheus 3000:Grafana 9093:Alertmanager)
    SERVICE=$(echo "${SERVICE_MAP[@]}" | grep -o "$port:[^ ]*" | cut -d: -f2)
    
    if ss -tuln | grep -q ":$port "; then
        PROCESS=$(sudo lsof -i :$port 2>/dev/null | awk 'NR==2 {print $1}' || echo "unknown")
        echo "OCCUPIED Port $port ($SERVICE): OCCUPIED by $PROCESS"
    else
        echo "FREE Port $port ($SERVICE): Available"
    fi
done

# 3. Системные лимиты
echo -e "\n[System Limits]"
SOFT_LIMIT=$(ulimit -Sn)
echo "File descriptors: $SOFT_LIMIT $([ $SOFT_LIMIT -ge 65536 ] && echo OK || echo 'WARNING Need: 65536')"

# 4. Docker/K8s
echo -e "\n[Container Platform]"
command -v docker &>/dev/null && echo "Docker: $(docker version --format '{{.Server.Version}}')" || echo "Docker: Not installed"
command -v kubectl &>/dev/null && echo "Kubernetes: $(kubectl version --client -o json | jq -r .clientVersion.gitVersion)" || echo "Kubernetes: Not installed"

echo -e "\n=== Diagnostic Complete. Full log: diagnostic.log ==="
```

**Пример вывода:**
```
=== SYSTEM DIAGNOSTIC 2025-01-15 10:23:45 ===
[Resources]
Memory: 6GB available OK
Disk: 67% used OK
CPU: 8 cores, Load: 2.15

[Port Check]
OCCUPIED Port 9090 (Prometheus): OCCUPIED by prometheus
FREE Port 3000 (Grafana): Available
FREE Port 9093 (Alertmanager): Available

[System Limits]
File descriptors: 1024 WARNING Need: 65536

[Container Platform]
Docker: 24.0.7
Kubernetes: v1.28.4
```

## Часть 2: Python-анализатор для углубленной проверки

Для комплексного анализа используем Python-скрипт с автоматическим исправлением конфликтов:

**🔗 [Скачать monitoring-analyzer.py](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/scripts/monitoring-analyzer.py)**

```python
#!/usr/bin/env python3
# monitoring-analyzer.py - Интеллектуальный анализ и автофикс
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

import json
import socket
import subprocess
from datetime import datetime

class MonitoringAnalyzer:
    def __init__(self):
        self.monitoring_ports = {
            9090: "prometheus", 3000: "grafana", 
            9093: "alertmanager", 9100: "node-exporter"
        }
        self.issues = []
        
    def analyze(self):
        """Основной метод анализа"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'ports': self.check_ports(),
            'resources': self.check_resources(),
            'docker': self.check_docker(),
            'readiness_score': 100
        }
        
        # Расчет готовности
        report['readiness_score'] -= len(self.issues) * 10
        report['issues'] = self.issues
        
        # Генерация фикса если есть проблемы
        if self.issues:
            report['fixes'] = self.generate_fixes()
            
        return report
    
    def check_ports(self):
        """Проверка доступности портов"""
        results = {}
        for port, service in self.monitoring_ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                self.issues.append(f"Port {port} occupied")
                results[port] = {'status': 'occupied', 'service': service}
            else:
                results[port] = {'status': 'free', 'service': service}
            sock.close()
            
        return results
    
    def check_resources(self):
        """Проверка системных ресурсов"""
        # Память
        mem_check = subprocess.check_output(
            "free -g | awk 'NR==2 {print $7}'", shell=True
        ).decode().strip()
        available_gb = int(mem_check)
        
        if available_gb < 2:
            self.issues.append(f"Low memory: {available_gb}GB")
            
        return {'memory_gb': available_gb, 'sufficient': available_gb >= 2}
    
    def check_docker(self):
        """Проверка Docker окружения"""
        try:
            # Проверка запущенных контейнеров мониторинга
            containers = subprocess.check_output(
                "docker ps --format '{{.Names}}' | grep -E 'prometheus|grafana' || true",
                shell=True
            ).decode().strip().split('\n')
            
            # Проверка volumes
            volumes = subprocess.check_output(
                "docker volume ls --format '{{.Name}}' | grep -E 'prometheus|grafana' || true",
                shell=True
            ).decode().strip().split('\n')
            
            return {
                'running_containers': [c for c in containers if c],
                'existing_volumes': [v for v in volumes if v]
            }
        except:
            return {'error': 'Docker not available'}
    
    def generate_fixes(self):
        """Генерация исправлений"""
        fixes = []
        
        for issue in self.issues:
            if "Port 9090" in issue:
                fixes.append({
                    'issue': issue,
                    'fix': 'Use port 9091 or stop existing Prometheus',
                    'command': 'docker stop prometheus || sudo kill $(lsof -t -i:9090)'
                })
            elif "Low memory" in issue:
                fixes.append({
                    'issue': issue,
                    'fix': 'Free up memory or increase RAM',
                    'command': 'docker system prune -a -f'
                })
                
        return fixes

if __name__ == "__main__":
    analyzer = MonitoringAnalyzer()
    report = analyzer.analyze()
    
    print(f"\n📊 Readiness Score: {report['readiness_score']}%")
    
    if report['issues']:
        print("\n⚠️ Issues found:")
        for issue in report['issues']:
            print(f"  - {issue}")
            
        print("\n🔧 Suggested fixes:")
        for fix in report['fixes']:
            print(f"  - {fix['fix']}")
            print(f"    Command: {fix['command']}")
    else:
        print("\n✅ System ready for monitoring deployment")
    
    # Сохранение отчета
    with open('monitoring_analysis.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("\n📄 Full report: monitoring_analysis.json")
```

## Часть 3: Решение основных критических проблем

### Проблема #1: Конфликт портов

**Техническая суть:**
Prometheus требует биндинга на порт 9090. При наличии другого процесса на этом порту Docker/systemd не может запустить сервис.

**Диагностика:**
```bash
# Проверка занятости порта
ss -tuln | grep :9090
# Поиск процесса
sudo lsof -i :9090
```

**Решения:**
1. **Освобождение порта:**
```bash
sudo kill $(lsof -t -i:9090)
```

2. **Использование альтернативного порта:**
```yaml
# docker-compose.yml
services:
  prometheus:
    ports:
      - "9091:9090"  # внешний порт 9091, внутренний 9090
```

### Проблема #2: Недостаток файловых дескрипторов

**Техническая суть:**
Prometheus открывает множество файлов для хранения time series данных. Системный лимит по умолчанию (обычно 1024) недостаточен для production нагрузки.

**Диагностика:**
```bash
# Текущие лимиты
ulimit -n          # soft limit
ulimit -Hn         # hard limit
# Использование процессом
cat /proc/$(pidof prometheus)/limits | grep "Max open files"
```

**Решение:**
```bash
# Постоянное увеличение лимитов
echo "* soft nofile 65536
* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Для systemd служб
mkdir -p /etc/systemd/system/prometheus.service.d/
echo "[Service]
LimitNOFILE=65536" | sudo tee /etc/systemd/system/prometheus.service.d/limits.conf

# Перезагрузка конфигурации
sudo systemctl daemon-reload
```

### Проблема #3: Конфликт Docker volumes

**Техническая суть:**
При переустановке monitoring stack данные Prometheus/Grafana теряются из-за пересоздания volumes. Также возможны конфликты имен volumes между различными проектами.

**Диагностика:**
```bash
# Проверка существующих volumes
docker volume ls | grep -E "(prometheus|grafana)"
# Анализ использования
docker volume inspect prometheus_data
```

**Решение:**
```yaml
# docker-compose.yml с именованными volumes
version: '3.8'
services:
  prometheus:
    volumes:
      - prometheus_data:/prometheus
  grafana:
    volumes:
      - grafana_data:/var/lib/grafana
      
volumes:
  prometheus_data:
    external: true  # использовать существующий volume
  grafana_data:
    external: true
```

**Создание persistent volumes:**
```bash
docker volume create prometheus_data
docker volume create grafana_data
```

## Часть 4: Интеграция с CI/CD

### Обоснование автоматизации диагностики

**Проблема:** Ручная диагностика занимает время и подвержена human errors.

**Решение:** Включение диагностических проверок в CI/CD pipeline гарантирует, что деплой мониторинга произойдет только при готовности инфраструктуры.

### GitLab CI Pipeline

**🔗 [Скачать gitlab-ci.yml](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/ci-cd/gitlab-ci.yml)**

```yaml
# .gitlab-ci.yml
stages:
  - diagnostic
  - deploy

monitoring-check:
  stage: diagnostic
  script:
    - ./diagnostic.sh
    - python3 monitoring-analyzer.py
    - |
      SCORE=$(jq -r '.readiness_score' monitoring_analysis.json)
      if [ "$SCORE" -lt 70 ]; then
        echo "❌ Not ready. Score: $SCORE%"
        exit 1
      fi
  artifacts:
    reports:
      junit: diagnostic.log
    paths:
      - monitoring_analysis.json
    when: always

deploy-monitoring:
  stage: deploy
  dependencies:
    - monitoring-check
  script:
    - docker-compose up -d
    - curl -f http://localhost:9090/-/healthy
  only:
    - main
```

## Часть 5: Мониторинг по Four Golden Signals

После успешной диагностики настраиваем мониторинг по методологии SRE:

**🔗 [Готовые правила мониторинга](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/templates/prometheus-rules.yml)**

```yaml
# prometheus-rules.yml
groups:
  - name: golden_signals
    rules:
      # Latency
      - alert: HighLatency
        expr: histogram_quantile(0.95, http_request_duration_seconds_bucket) > 0.5
        
      # Traffic  
      - alert: TrafficSpike
        expr: rate(http_requests_total[5m]) > 1000
        
      # Errors
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        
      # Saturation
      - alert: HighMemory
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) > 0.9
```

## Преимущества методологии

Проведение диагностики перед развертыванием мониторинга позволяет:

- Сократить время на устранение проблем
- Предотвратить потерю данных мониторинга
- Уменьшить количество инцидентов при развертывании
- Обеспечить стабильную работу мониторинга с первого дня

## 🎯 Быстрый старт

### 1. Клонируйте репозиторий
```bash
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git
cd DevOpsBestPractices
```

### 2. Запустите диагностику
```bash
# Bash-скрипт (быстро)
chmod +x code/monitoring-diagnostics/scripts/mega-diagnostic.sh
./code/monitoring-diagnostics/scripts/mega-diagnostic.sh

# Python-анализатор (детально)  
python3 code/monitoring-diagnostics/scripts/monitoring-analyzer.py
```

### 3. Демо-версия
```bash
# Интерактивная демонстрация
chmod +x examples/monitoring-diagnostics/quick-start.sh
./examples/monitoring-diagnostics/quick-start.sh
```

### 4. Развертывание мониторинга
```bash
# После успешной диагностики
docker-compose -f code/monitoring-diagnostics/templates/docker-compose.yml up -d
```

## Чек-лист готовности

- [ ] **Ресурсы**
  - [ ] RAM ≥ 2GB available
  - [ ] Disk usage < 85%
  - [ ] CPU load < cores count

- [ ] **Порты**
  - [ ] 9090 (Prometheus) свободен или идентифицирован
  - [ ] 3000 (Grafana) доступен
  - [ ] Firewall правила настроены

- [ ] **Системные настройки**
  - [ ] File descriptors ≥ 65536
  - [ ] Docker daemon запущен
  - [ ] Нет конфликтов volumes

- [ ] **CI/CD**
  - [ ] Диагностический pipeline настроен
  - [ ] Автоматические проверки работают

## Полезные ресурсы

- [GitHub: Все скрипты из статьи](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/tree/main/code/monitoring-diagnostics)
- [Telegram: @DevOps_best_practices](https://t.me/DevOps_best_practices)

## Заключение

Правильная диагностика инфраструктуры перед развертыванием мониторинга является важным этапом, который позволяет сэкономить значительное время на дальнейшее устранение проблем и предотвращает потерю критических метрик.

Используя представленные инструменты, вы сможете:

- **Сократить время развертывания** мониторинга
- **Предотвратить типичные проблемы** конфигурации
- **Масштабировать мониторинг без конфликтов**
- **Автоматизировать процесс через CI/CD**

> 💡 **Помните**: час диагностики экономит день отладки.

---

**Все скрипты протестированы на Ubuntu 20.04/22.04, CentOS 7/8, Kubernetes 1.20+.**

**Автор**: DevOps-best-practices Team  
**GitHub**: [monitoring-diagnostics](https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/tree/main/code/monitoring-diagnostics)  
**Обратная связь**: [Telegram канал](https://t.me/DevOps_best_practices)

---

**Теги**: #DevOps #Prometheus #Grafana #Monitoring #Docker #Kubernetes #BestPractices #SRE #Диагностика #Автоматизация #CI_CD #Production #Linux #SystemAdmin #Infrastructure