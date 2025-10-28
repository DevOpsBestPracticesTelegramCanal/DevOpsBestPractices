#!/bin/bash
# quick-start.sh - Быстрый запуск демонстрации диагностики мониторинга
# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
# Telegram: @DevOps_best_practices

set -euo pipefail

# Цвета
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🚀 DevOps Best Practices - Monitoring Diagnostics Demo${NC}"
echo -e "${BLUE}📁 GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices${NC}"
echo -e "${BLUE}💬 Telegram: @DevOps_best_practices${NC}"
echo ""

# Проверка зависимостей
check_dependencies() {
    echo -e "${BLUE}🔍 Проверка зависимостей...${NC}"
    
    local deps=("bash" "python3" "docker")
    local missing=()
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            missing+=("$dep")
        fi
    done
    
    if [ ${#missing[@]} -ne 0 ]; then
        echo -e "${YELLOW}⚠️ Отсутствуют зависимости: ${missing[*]}${NC}"
        echo "Установите их перед запуском демо"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Все зависимости установлены${NC}"
}

# Функция демонстрации
run_demo() {
    echo ""
    echo -e "${BLUE}📋 Что будет продемонстрировано:${NC}"
    echo "1. 🔍 Bash-скрипт диагностики (mega-diagnostic.sh)"
    echo "2. 🐍 Python анализатор (monitoring-analyzer.py)"
    echo "3. 📊 Отчеты и рекомендации"
    echo ""
    
    read -p "Продолжить? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Демо отменено"
        exit 0
    fi
    
    echo ""
    echo -e "${BLUE}🔥 Запуск демонстрации...${NC}"
    
    # 1. Bash диагностика
    echo ""
    echo -e "${BLUE}1️⃣ Запуск bash-диагностики...${NC}"
    if [ -f "../code/monitoring-diagnostics/scripts/mega-diagnostic.sh" ]; then
        chmod +x "../code/monitoring-diagnostics/scripts/mega-diagnostic.sh"
        bash "../code/monitoring-diagnostics/scripts/mega-diagnostic.sh"
    else
        echo -e "${YELLOW}⚠️ Скрипт mega-diagnostic.sh не найден${NC}"
    fi
    
    echo ""
    echo -e "${BLUE}Нажмите Enter для продолжения...${NC}"
    read
    
    # 2. Python анализатор
    echo ""
    echo -e "${BLUE}2️⃣ Запуск Python анализатора...${NC}"
    if [ -f "../code/monitoring-diagnostics/scripts/monitoring-analyzer.py" ]; then
        python3 "../code/monitoring-diagnostics/scripts/monitoring-analyzer.py"
    else
        echo -e "${YELLOW}⚠️ Скрипт monitoring-analyzer.py не найден${NC}"
    fi
    
    echo ""
    echo -e "${BLUE}Нажмите Enter для продолжения...${NC}"
    read
    
    # 3. Показать файлы результатов
    echo ""
    echo -e "${BLUE}3️⃣ Результаты диагностики:${NC}"
    
    if [ -f "diagnostic.log" ]; then
        echo -e "${GREEN}📄 diagnostic.log создан${NC}"
        echo "Последние 10 строк:"
        tail -10 diagnostic.log
    fi
    
    if [ -f "diagnostic_report.json" ]; then
        echo -e "${GREEN}📊 diagnostic_report.json создан${NC}"
        if command -v jq >/dev/null 2>&1; then
            echo "Оценка готовности:"
            jq '.readiness_score' diagnostic_report.json
        fi
    fi
    
    echo ""
    local analysis_file=$(ls monitoring_analysis_*.json 2>/dev/null | head -1 || echo "")
    if [ -n "$analysis_file" ]; then
        echo -e "${GREEN}🐍 $analysis_file создан${NC}"
        if command -v jq >/dev/null 2>&1; then
            echo "Статус системы:"
            jq '.summary.message' "$analysis_file"
        fi
    fi
}

# Показать следующие шаги
show_next_steps() {
    echo ""
    echo -e "${BLUE}🎯 Следующие шаги:${NC}"
    echo ""
    echo "1. 📖 Изучите полные отчеты:"
    echo "   - diagnostic.log - подробный лог диагностики"
    echo "   - diagnostic_report.json - JSON отчет для автоматизации"
    echo "   - monitoring_analysis_*.json - результаты Python анализатора"
    echo ""
    echo "2. 🔧 Если найдены проблемы, используйте скрипты исправления:"
    echo "   - ../code/monitoring-diagnostics/scripts/fixes/"
    echo ""
    echo "3. 🚀 Развертывание мониторинга:"
    echo "   - docker-compose -f ../code/monitoring-diagnostics/templates/docker-compose.yml up -d"
    echo ""
    echo "4. 📚 Документация и примеры:"
    echo "   - https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices"
    echo ""
    echo "5. 💬 Поддержка:"
    echo "   - Telegram: @DevOps_best_practices"
    echo ""
}

# Очистка файлов демо
cleanup_demo() {
    echo ""
    read -p "Удалить файлы демо? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -f diagnostic.log diagnostic_report.json monitoring_analysis_*.json
        echo -e "${GREEN}🧹 Файлы демо удалены${NC}"
    fi
}

# Главная функция
main() {
    check_dependencies
    run_demo
    show_next_steps
    cleanup_demo
    
    echo ""
    echo -e "${GREEN}✨ Демо завершено! Спасибо за использование DevOps Best Practices${NC}"
}

# Обработка прерывания
trap 'echo -e "\n⛔ Демо прервано пользователем"; exit 1' INT

# Запуск
main "$@"