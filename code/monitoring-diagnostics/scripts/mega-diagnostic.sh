#!/bin/bash
# mega-diagnostic.sh - Полная диагностика системы за один запуск
# Версия: 1.0
# Автор: DevOpsBestPractices Team
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция логирования
log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1" | tee -a diagnostic.log
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a diagnostic.log
}

success() {
    echo -e "${GREEN}✅ $1${NC}" | tee -a diagnostic.log
}

warning() {
    echo -e "${YELLOW}⚠️ $1${NC}" | tee -a diagnostic.log
}

echo "=== SYSTEM DIAGNOSTIC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee diagnostic.log
echo "GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices" | tee -a diagnostic.log
echo "Telegram: @DevOps_best_practices" | tee -a diagnostic.log
echo "" | tee -a diagnostic.log

# 1. Проверка ресурсов
log "Проверка системных ресурсов..."

# Память
if command -v free >/dev/null 2>&1; then
    AVAILABLE_MEM=$(free -g | awk 'NR==2 {print $7}' 2>/dev/null || echo "0")
    if [ "$AVAILABLE_MEM" -ge 2 ]; then
        success "Память: ${AVAILABLE_MEM}GB доступно"
    else
        warning "Память: ${AVAILABLE_MEM}GB доступно (рекомендуется ≥2GB)"
    fi
else
    warning "Команда 'free' недоступна (возможно, не Linux система)"
fi

# Диск
ROOT_USAGE=$(df -h / 2>/dev/null | awk 'NR==2 {print $5}' | sed 's/%//' || echo "0")
if [ "$ROOT_USAGE" -lt 85 ]; then
    success "Диск: ${ROOT_USAGE}% использовано"
else
    warning "Диск: ${ROOT_USAGE}% использовано (рекомендуется <85%)"
fi

# CPU
CPU_CORES=$(nproc 2>/dev/null || echo "unknown")
if command -v uptime >/dev/null 2>&1; then
    LOAD_AVG=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//' 2>/dev/null || echo "unknown")
    log "CPU: ${CPU_CORES} ядер, Нагрузка: ${LOAD_AVG}"
else
    log "CPU: ${CPU_CORES} ядер"
fi

# 2. Проверка портов
echo "" | tee -a diagnostic.log
log "Проверка критических портов..."

declare -A SERVICE_MAP
SERVICE_MAP[9090]="Prometheus"
SERVICE_MAP[3000]="Grafana" 
SERVICE_MAP[9093]="Alertmanager"
SERVICE_MAP[9100]="Node Exporter"

for port in "${!SERVICE_MAP[@]}"; do
    service="${SERVICE_MAP[$port]}"
    
    if command -v ss >/dev/null 2>&1; then
        if ss -tuln 2>/dev/null | grep -q ":$port "; then
            if command -v lsof >/dev/null 2>&1; then
                PROCESS=$(sudo lsof -i :$port 2>/dev/null | awk 'NR==2 {print $1}' || echo "unknown")
                error "Порт $port ($service): ЗАНЯТ процессом $PROCESS"
            else
                error "Порт $port ($service): ЗАНЯТ"
            fi
        else
            success "Порт $port ($service): Доступен"
        fi
    else
        if command -v netstat >/dev/null 2>&1; then
            if netstat -tuln 2>/dev/null | grep -q ":$port "; then
                error "Порт $port ($service): ЗАНЯТ"
            else
                success "Порт $port ($service): Доступен"
            fi
        else
            warning "Невозможно проверить порт $port - нет ss/netstat"
        fi
    fi
done

# 3. Системные лимиты
echo "" | tee -a diagnostic.log
log "Проверка системных лимитов..."

SOFT_LIMIT=$(ulimit -Sn 2>/dev/null || echo "unknown")
if [ "$SOFT_LIMIT" != "unknown" ] && [ "$SOFT_LIMIT" -ge 65536 ]; then
    success "Файловые дескрипторы: $SOFT_LIMIT"
else
    warning "Файловые дескрипторы: $SOFT_LIMIT (рекомендуется ≥65536)"
    echo "  Для увеличения выполните:" | tee -a diagnostic.log
    echo "  echo '* soft nofile 65536' | sudo tee -a /etc/security/limits.conf" | tee -a diagnostic.log
    echo "  echo '* hard nofile 65536' | sudo tee -a /etc/security/limits.conf" | tee -a diagnostic.log
fi

# 4. Проверка Docker/Kubernetes
echo "" | tee -a diagnostic.log
log "Проверка контейнерных платформ..."

if command -v docker >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
        DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
        success "Docker: v${DOCKER_VERSION}"
        
        # Проверка запущенных контейнеров мониторинга
        MONITORING_CONTAINERS=$(docker ps --format "{{.Names}}" 2>/dev/null | grep -E "(prometheus|grafana|alertmanager)" | wc -l || echo "0")
        if [ "$MONITORING_CONTAINERS" -gt 0 ]; then
            warning "Найдено $MONITORING_CONTAINERS запущенных контейнеров мониторинга"
            docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(prometheus|grafana|alertmanager)" | tee -a diagnostic.log
        fi
    else
        error "Docker установлен, но недоступен (проверьте права доступа)"
    fi
else
    warning "Docker: Не установлен"
fi

if command -v kubectl >/dev/null 2>&1; then
    if kubectl version --client >/dev/null 2>&1; then
        K8S_VERSION=$(kubectl version --client -o json 2>/dev/null | grep -o '"gitVersion":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
        success "Kubernetes: ${K8S_VERSION}"
    else
        warning "kubectl установлен, но недоступен"
    fi
else
    warning "Kubernetes: Не установлен"
fi

# 5. Проверка volumes (для Docker)
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "" | tee -a diagnostic.log
    log "Проверка Docker volumes..."
    
    MONITORING_VOLUMES=$(docker volume ls --format "{{.Name}}" 2>/dev/null | grep -E "(prometheus|grafana)" | wc -l || echo "0")
    if [ "$MONITORING_VOLUMES" -gt 0 ]; then
        warning "Найдено $MONITORING_VOLUMES существующих volumes мониторинга"
        docker volume ls --format "table {{.Name}}\t{{.Driver}}" | grep -E "(prometheus|grafana)" | tee -a diagnostic.log
    else
        success "Конфликтующие volumes не найдены"
    fi
fi

# 6. Финальная оценка готовности
echo "" | tee -a diagnostic.log
log "Расчет готовности системы..."

READINESS_SCORE=100
ISSUES=0

# Подсчет проблем из лога
WARNINGS=$(grep -c "⚠️" diagnostic.log || echo "0")
ERRORS=$(grep -c "❌" diagnostic.log || echo "0")

READINESS_SCORE=$((READINESS_SCORE - WARNINGS * 10 - ERRORS * 20))
ISSUES=$((WARNINGS + ERRORS))

echo "" | tee -a diagnostic.log
echo "=================== РЕЗУЛЬТАТ ===================" | tee -a diagnostic.log
echo -e "${BLUE}📊 Оценка готовности: ${READINESS_SCORE}%${NC}" | tee -a diagnostic.log
echo -e "${BLUE}⚠️  Предупреждений: ${WARNINGS}${NC}" | tee -a diagnostic.log
echo -e "${BLUE}❌ Критических проблем: ${ERRORS}${NC}" | tee -a diagnostic.log

if [ "$READINESS_SCORE" -ge 80 ]; then
    echo -e "${GREEN}✅ Система готова к развертыванию мониторинга${NC}" | tee -a diagnostic.log
elif [ "$READINESS_SCORE" -ge 60 ]; then
    echo -e "${YELLOW}⚠️ Система требует минимальных исправлений${NC}" | tee -a diagnostic.log
else
    echo -e "${RED}❌ Система НЕ готова. Необходимы исправления${NC}" | tee -a diagnostic.log
fi

echo "" | tee -a diagnostic.log
echo "📄 Полный отчет сохранен в: diagnostic.log" | tee -a diagnostic.log
echo "🔧 Инструкции по исправлению: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/tree/main/code/monitoring-diagnostics" | tee -a diagnostic.log
echo "💬 Поддержка: @DevOps_best_practices" | tee -a diagnostic.log

# Генерация JSON отчета для автоматизации
cat > diagnostic_report.json << EOF
{
  "timestamp": "$(date -Iseconds)",
  "readiness_score": $READINESS_SCORE,
  "warnings": $WARNINGS,
  "errors": $ERRORS,
  "system_info": {
    "available_memory_gb": "${AVAILABLE_MEM:-unknown}",
    "disk_usage_percent": "${ROOT_USAGE:-unknown}",
    "cpu_cores": "${CPU_CORES:-unknown}",
    "load_average": "${LOAD_AVG:-unknown}"
  },
  "docker_available": $(command -v docker >/dev/null 2>&1 && echo "true" || echo "false"),
  "kubernetes_available": $(command -v kubectl >/dev/null 2>&1 && echo "true" || echo "false")
}
EOF

echo "📊 JSON отчет: diagnostic_report.json" | tee -a diagnostic.log

exit 0