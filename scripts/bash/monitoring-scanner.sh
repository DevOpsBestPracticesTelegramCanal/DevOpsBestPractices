#!/bin/bash
# 🔍 DevOps Multi-Project Monitoring Scanner v2.0
# Автоматическое обнаружение всех Prometheus/Grafana установок

echo "═══════════════════════════════════════════════════════════════"
echo "🔍 DevOps Multi-Project Monitoring Scanner"
echo "═══════════════════════════════════════════════════════════════"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Функция проверки портов
check_ports() {
    echo -e "\n📊 СКАНИРОВАНИЕ ПОРТОВ МОНИТОРИНГА:"
    echo "─────────────────────────────────────"
    
    # Проверяем стандартные порты
    MONITORING_PORTS=(3000 9090 9091 9092 9093 3001 3002)
    
    for port in "${MONITORING_PORTS[@]}"; do
        if ss -tulpn | grep ":$port " > /dev/null 2>&1; then
            PROCESS=$(ss -tulpn | grep ":$port " | awk '{print $6}' | cut -d'"' -f2)
            echo -e "${YELLOW}⚠ Порт $port занят:${NC} $PROCESS"
            
            # Определяем что за сервис
            if [[ "$PROCESS" == *"prometheus"* ]]; then
                echo -e "  └─ ${GREEN}Prometheus обнаружен${NC}"
            elif [[ "$PROCESS" == *"grafana"* ]]; then
                echo -e "  └─ ${GREEN}Grafana обнаружена${NC}"
            fi
        else
            echo -e "✅ Порт $port свободен"
        fi
    done
}

# Функция поиска Docker контейнеров
scan_docker_containers() {
    echo -e "\n🐳 DOCKER КОНТЕЙНЕРЫ МОНИТОРИНГА:"
    echo "─────────────────────────────────────"
    
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker не установлен${NC}"
        return
    fi
    
    # Поиск Prometheus контейнеров
    echo -e "\n${YELLOW}Prometheus контейнеры:${NC}"
    docker ps -a --filter "name=prometheus" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -10
    
    # Поиск Grafana контейнеров  
    echo -e "\n${YELLOW}Grafana контейнеры:${NC}"
    docker ps -a --filter "name=grafana" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -10
}

# Функция поиска volumes
check_docker_volumes() {
    echo -e "\n💾 DOCKER VOLUMES МОНИТОРИНГА:"
    echo "─────────────────────────────────────"
    
    if ! command -v docker &> /dev/null; then
        return
    fi
    
    echo -e "${YELLOW}Prometheus volumes:${NC}"
    docker volume ls | grep -i prometheus 2>/dev/null | awk '{print "  - "$2}'
    
    echo -e "\n${YELLOW}Grafana volumes:${NC}"
    docker volume ls | grep -i grafana 2>/dev/null | awk '{print "  - "$2}'
}

# Функция быстрой диагностики проблем
quick_diagnostic() {
    echo -e "\n⚡ БЫСТРАЯ ДИАГНОСТИКА:"
    echo "─────────────────────────────────────"
    
    # Проверка доступности Prometheus
    if command -v curl &> /dev/null && curl -s http://localhost:9090/-/healthy >/dev/null 2>&1; then
        echo -e "✅ Prometheus доступен на порту 9090"
    else
        echo -e "${RED}✗ Prometheus недоступен на порту 9090${NC}"
    fi
    
    # Проверка доступности Grafana
    if command -v curl &> /dev/null && curl -s http://localhost:3000/api/health >/dev/null 2>&1; then
        echo -e "✅ Grafana доступна на порту 3000"
    else
        echo -e "${RED}✗ Grafana недоступна на порту 3000${NC}"
    fi
}

# Функция генерации отчета
generate_report() {
    echo -e "\n📊 ИТОГОВЫЙ ОТЧЕТ:"
    echo "═══════════════════════════════════════════════════════════════"
    
    # Подсчитываем найденные экземпляры
    if command -v docker &> /dev/null; then
        PROM_COUNT=$(docker ps 2>/dev/null | grep -c prometheus || echo 0)
        GRAF_COUNT=$(docker ps 2>/dev/null | grep -c grafana || echo 0)
    else
        PROM_COUNT=0
        GRAF_COUNT=0
    fi
    
    echo -e "Найдено активных экземпляров:"
    echo -e "  • Prometheus: ${YELLOW}$PROM_COUNT${NC}"
    echo -e "  • Grafana: ${YELLOW}$GRAF_COUNT${NC}"
    
    if [ $PROM_COUNT -gt 1 ] || [ $GRAF_COUNT -gt 1 ]; then
        echo -e "\n${RED}⚠ ВНИМАНИЕ: Обнаружены множественные экземпляры!${NC}"
        echo "Рекомендации:"
        echo "  1. Используйте разные порты для каждого проекта"
        echo "  2. Создайте уникальные имена контейнеров"
        echo "  3. Используйте отдельные volumes для данных"
        echo "  4. Настройте federation для объединения метрик"
    fi
    
    # Сохраняем отчет
    REPORT_FILE="monitoring_scan_$(date +%Y%m%d_%H%M%S).txt"
    echo -e "\n📄 Отчет будет сохранен в: $REPORT_FILE"
}

# Главное меню
main() {
    check_ports
    scan_docker_containers
    check_docker_volumes
    quick_diagnostic
    generate_report
    
    echo -e "\n✅ Сканирование завершено!"
}

# Запуск
main
