#!/usr/bin/env python3
"""
🔍 Smart DevOps Monitoring Analyzer v3.0
Интеллектуальный анализатор Prometheus/Grafana проектов
"""

import os
import json
import subprocess
import socket
from datetime import datetime

print("🔍 Smart DevOps Monitoring Analyzer v3.0")
print("=" * 50)

def check_port(port):
    """Проверка занятости порта"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
    except:
        return False

def scan_monitoring_ports():
    """Сканирование портов мониторинга"""
    print("\n📊 СКАНИРОВАНИЕ ПОРТОВ МОНИТОРИНГА:")
    print("-" * 40)
    
    monitoring_ports = {
        'Prometheus': [9090, 9091, 9092, 9093],
        'Grafana': [3000, 3001, 3002, 3003],
        'Alertmanager': [9093, 9094],
        'Node Exporter': [9100, 9101]
    }
    
    for service, ports in monitoring_ports.items():
        print(f"\n{service}:")
        for port in ports:
            if check_port(port):
                print(f"  ⚠  Порт {port}: занят")
            else:
                print(f"  ✅ Порт {port}: свободен")

def check_docker_containers():
    """Проверка Docker контейнеров"""
    print("\n🐳 DOCKER КОНТЕЙНЕРЫ МОНИТОРИНГА:")
    print("-" * 40)
    
    try:
        # Проверяем Prometheus контейнеры
        result = subprocess.run([
            'docker', 'ps', '-a', 
            '--filter', 'name=prometheus'
        ], capture_output=True, text=True)
        
        if "prometheus" in result.stdout.lower():
            print("Prometheus контейнеры найдены")
        else:
            print("Prometheus контейнеры не найдены")
            
        # Проверяем Grafana контейнеры
        result = subprocess.run([
            'docker', 'ps', '-a',
            '--filter', 'name=grafana'
        ], capture_output=True, text=True)
        
        if "grafana" in result.stdout.lower():
            print("Grafana контейнеры найдены")
        else:
            print("Grafana контейнеры не найдены")
            
    except Exception as e:
        print(f"Ошибка проверки Docker: {e}")

def quick_health_check():
    """Быстрая проверка здоровья сервисов"""
    print("\n⚡ БЫСТРАЯ ДИАГНОСТИКА:")
    print("-" * 40)
    
    # Проверка Prometheus
    if check_port(9090):
        print("✅ Prometheus порт 9090 активен")
    else:
        print("❌ Prometheus порт 9090 неактивен")
    
    # Проверка Grafana
    if check_port(3000):
        print("✅ Grafana порт 3000 активен")
    else:
        print("❌ Grafana порт 3000 неактивен")

def generate_report():
    """Генерация итогового отчета"""
    print("\n📊 ИТОГОВЫЙ ОТЧЕТ:")
    print("=" * 50)
    
    # Подсчет найденных сервисов
    prom_count = sum(1 for port in [9090, 9091, 9092, 9093] if check_port(port))
    grafana_count = sum(1 for port in [3000, 3001, 3002, 3003] if check_port(port))
    
    print(f"Найдено активных экземпляров:")
    print(f"  • Prometheus: {prom_count}")
    print(f"  • Grafana: {grafana_count}")
    
    if prom_count > 1 or grafana_count > 1:
        print("\n⚠  ВНИМАНИЕ: Обнаружены множественные экземпляры!")
        print("Рекомендации:")
        print("  1. Используйте разные порты для каждого проекта")
        print("  2. Настройте Federation для объединения метрик")
    
    # Сохраняем отчет
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f'monitoring_python_report_{timestamp}.json'
    
    report_data = {
        'timestamp': timestamp,
        'prometheus_instances': prom_count,
        'grafana_instances': grafana_count,
        'status': 'analysis_completed'
    }
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Отчет сохранен: {report_file}")

def main():
    """Главная функция"""
    scan_monitoring_ports()
    check_docker_containers() 
    quick_health_check()
    generate_report()
    print("\n✅ Анализ завершен!")

if __name__ == "__main__":
    main()
