#!/usr/bin/env python3
"""
monitoring-analyzer.py - Интеллектуальный анализатор готовности системы к мониторингу
Версия: 1.0
Автор: DevOpsBestPractices Team
GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
"""

import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SystemChecker:
    """Базовый класс для проверок системы"""
    
    def __init__(self):
        self.issues: List[str] = []
        self.warnings: List[str] = []
    
    def run_command(self, cmd: str) -> Tuple[bool, str]:
        """Безопасное выполнение команды"""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, 
                text=True, timeout=30
            )
            return result.returncode == 0, result.stdout.strip()
        except (subprocess.TimeoutExpired, Exception) as e:
            return False, str(e)


class MonitoringAnalyzer(SystemChecker):
    """Главный анализатор системы мониторинга"""
    
    def __init__(self):
        super().__init__()
        self.monitoring_ports = {
            9090: "prometheus", 
            3000: "grafana", 
            9093: "alertmanager", 
            9100: "node-exporter",
            9115: "blackbox-exporter"
        }
        self.required_memory_gb = 2
        self.required_disk_free_percent = 15
        self.required_file_descriptors = 65536
        
    def analyze(self) -> Dict:
        """Основной метод анализа системы"""
        print("🔍 Запуск интеллектуального анализа системы...")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'analyzer_version': '1.0',
            'github_repo': 'https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices',
            'telegram': '@DevOps_best_practices',
            'checks': {
                'ports': self._check_ports(),
                'resources': self._check_resources(),
                'system_limits': self._check_system_limits(),
                'docker': self._check_docker(),
                'kubernetes': self._check_kubernetes(),
                'monitoring_conflicts': self._check_existing_monitoring()
            }
        }
        
        # Расчет итоговой готовности
        report['summary'] = self._calculate_readiness(report['checks'])
        
        # Генерация рекомендаций
        if self.issues or self.warnings:
            report['recommendations'] = self._generate_recommendations()
            
        return report
    
    def _check_ports(self) -> Dict:
        """Проверка доступности портов"""
        print("  📡 Проверка портов...")
        results = {}
        
        for port, service in self.monitoring_ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            
            try:
                result = sock.connect_ex(('127.0.0.1', port))
                if result == 0:
                    self.issues.append(f"Порт {port} ({service}) занят")
                    process_info = self._get_port_process(port)
                    results[port] = {
                        'status': 'occupied', 
                        'service': service,
                        'process': process_info
                    }
                else:
                    results[port] = {'status': 'free', 'service': service}
            except Exception as e:
                self.warnings.append(f"Ошибка проверки порта {port}: {e}")
                results[port] = {'status': 'error', 'service': service, 'error': str(e)}
            finally:
                sock.close()
                
        return results
    
    def _get_port_process(self, port: int) -> Optional[str]:
        """Получение информации о процессе, использующем порт"""
        try:
            success, output = self.run_command(f"lsof -i :{port} -t")
            if success and output:
                pid = output.split('\n')[0]
                success, process_name = self.run_command(f"ps -p {pid} -o comm=")
                return process_name if success else f"PID:{pid}"
        except:
            pass
        return None
    
    def _check_resources(self) -> Dict:
        """Проверка системных ресурсов"""
        print("  💾 Проверка ресурсов...")
        results = {}
        
        # Память
        success, mem_output = self.run_command("free -g | awk 'NR==2 {print $7}'")
        if success:
            try:
                available_gb = int(mem_output)
                results['memory'] = {
                    'available_gb': available_gb,
                    'required_gb': self.required_memory_gb,
                    'sufficient': available_gb >= self.required_memory_gb
                }
                
                if available_gb < self.required_memory_gb:
                    self.issues.append(f"Недостаточно памяти: {available_gb}GB (требуется ≥{self.required_memory_gb}GB)")
            except ValueError:
                self.warnings.append("Не удалось определить доступную память")
                results['memory'] = {'error': 'parsing_failed'}
        else:
            results['memory'] = {'error': 'command_failed'}
        
        # Диск
        success, disk_output = self.run_command("df -h / | awk 'NR==2 {print $5}' | sed 's/%//'")
        if success:
            try:
                used_percent = int(disk_output)
                free_percent = 100 - used_percent
                results['disk'] = {
                    'used_percent': used_percent,
                    'free_percent': free_percent,
                    'required_free_percent': self.required_disk_free_percent,
                    'sufficient': free_percent >= self.required_disk_free_percent
                }
                
                if free_percent < self.required_disk_free_percent:
                    self.warnings.append(f"Мало свободного места: {free_percent}% (рекомендуется ≥{self.required_disk_free_percent}%)")
            except ValueError:
                results['disk'] = {'error': 'parsing_failed'}
        else:
            results['disk'] = {'error': 'command_failed'}
            
        return results
    
    def _check_system_limits(self) -> Dict:
        """Проверка системных лимитов"""
        print("  ⚙️ Проверка лимитов...")
        results = {}
        
        # Файловые дескрипторы
        success, fd_output = self.run_command("ulimit -Sn")
        if success:
            try:
                current_limit = int(fd_output)
                results['file_descriptors'] = {
                    'current': current_limit,
                    'required': self.required_file_descriptors,
                    'sufficient': current_limit >= self.required_file_descriptors
                }
                
                if current_limit < self.required_file_descriptors:
                    self.warnings.append(f"Низкий лимит файловых дескрипторов: {current_limit} (требуется ≥{self.required_file_descriptors})")
            except ValueError:
                results['file_descriptors'] = {'error': 'parsing_failed'}
        else:
            results['file_descriptors'] = {'error': 'command_failed'}
            
        return results
    
    def _check_docker(self) -> Dict:
        """Проверка Docker окружения"""
        print("  🐳 Проверка Docker...")
        results = {}
        
        # Проверка установки Docker
        success, version_output = self.run_command("docker --version")
        if not success:
            results['installed'] = False
            return results
            
        results['installed'] = True
        results['version'] = version_output
        
        # Проверка доступности Docker daemon
        success, _ = self.run_command("docker info")
        if not success:
            self.warnings.append("Docker установлен, но daemon недоступен")
            results['daemon_available'] = False
            return results
            
        results['daemon_available'] = True
        
        # Проверка запущенных контейнеров мониторинга
        success, containers_output = self.run_command(
            "docker ps --format '{{.Names}}' | grep -E '(prometheus|grafana|alertmanager)' || true"
        )
        if success:
            running_containers = [c for c in containers_output.split('\n') if c.strip()]
            results['running_monitoring_containers'] = running_containers
            
            if running_containers:
                self.warnings.append(f"Запущены контейнеры мониторинга: {', '.join(running_containers)}")
        
        # Проверка volumes
        success, volumes_output = self.run_command(
            "docker volume ls --format '{{.Name}}' | grep -E '(prometheus|grafana)' || true"
        )
        if success:
            existing_volumes = [v for v in volumes_output.split('\n') if v.strip()]
            results['existing_monitoring_volumes'] = existing_volumes
            
            if existing_volumes:
                self.warnings.append(f"Существуют volumes мониторинга: {', '.join(existing_volumes)}")
                
        return results
    
    def _check_kubernetes(self) -> Dict:
        """Проверка Kubernetes окружения"""
        print("  ☸️ Проверка Kubernetes...")
        results = {}
        
        # Проверка kubectl
        success, version_output = self.run_command("kubectl version --client --short")
        if not success:
            results['kubectl_installed'] = False
            return results
            
        results['kubectl_installed'] = True
        results['kubectl_version'] = version_output
        
        # Проверка доступности кластера
        success, cluster_info = self.run_command("kubectl cluster-info --request-timeout=5s")
        if success:
            results['cluster_available'] = True
            
            # Проверка namespace monitoring
            success, _ = self.run_command("kubectl get namespace monitoring")
            if success:
                self.warnings.append("Namespace 'monitoring' уже существует")
                results['monitoring_namespace_exists'] = True
            else:
                results['monitoring_namespace_exists'] = False
        else:
            results['cluster_available'] = False
            
        return results
    
    def _check_existing_monitoring(self) -> Dict:
        """Проверка существующих установок мониторинга"""
        print("  🔍 Поиск существующих установок...")
        results = {}
        
        # Поиск конфигурационных файлов
        config_paths = [
            '/etc/prometheus',
            '/opt/prometheus',
            '/usr/local/etc/prometheus',
            '~/.prometheus',
            '/etc/grafana',
            '/opt/grafana'
        ]
        
        found_configs = []
        for path in config_paths:
            expanded_path = Path(path).expanduser()
            if expanded_path.exists():
                found_configs.append(str(expanded_path))
                
        if found_configs:
            self.warnings.append(f"Найдены конфигурации мониторинга: {', '.join(found_configs)}")
            
        results['existing_configs'] = found_configs
        
        # Поиск системных сервисов
        services_to_check = ['prometheus', 'grafana-server', 'alertmanager']
        running_services = []
        
        for service in services_to_check:
            success, _ = self.run_command(f"systemctl is-active {service}")
            if success:
                running_services.append(service)
                
        if running_services:
            self.issues.append(f"Запущены сервисы мониторинга: {', '.join(running_services)}")
            
        results['running_services'] = running_services
        
        return results
    
    def _calculate_readiness(self, checks: Dict) -> Dict:
        """Расчет итоговой готовности системы"""
        score = 100
        critical_issues = len(self.issues)
        warnings_count = len(self.warnings)
        
        # Снижение баллов за проблемы
        score -= critical_issues * 20
        score -= warnings_count * 10
        
        score = max(0, score)  # Не меньше 0
        
        if score >= 80:
            status = "ready"
            message = "Система готова к развертыванию мониторинга"
        elif score >= 60:
            status = "ready_with_warnings"
            message = "Система готова, но требует внимания к предупреждениям"
        else:
            status = "not_ready"
            message = "Система НЕ готова. Необходимы исправления"
            
        return {
            'readiness_score': score,
            'status': status,
            'message': message,
            'critical_issues': critical_issues,
            'warnings': warnings_count,
            'total_checks': len(checks)
        }
    
    def _generate_recommendations(self) -> Dict:
        """Генерация рекомендаций по исправлению"""
        recommendations = {
            'critical': [],
            'warnings': [],
            'scripts': []
        }
        
        for issue in self.issues:
            if "Порт" in issue and "занят" in issue:
                port_num = issue.split()[1]
                recommendations['critical'].append({
                    'issue': issue,
                    'solution': f'Остановить процесс или использовать другой порт',
                    'commands': [
                        f'sudo lsof -i :{port_num}',
                        f'sudo kill $(lsof -t -i:{port_num})',
                        f'# Или использовать альтернативный порт в docker-compose'
                    ]
                })
            elif "памяти" in issue:
                recommendations['critical'].append({
                    'issue': issue,
                    'solution': 'Увеличить объем RAM или освободить память',
                    'commands': [
                        'free -h',
                        'docker system prune -a -f',
                        'sudo systemctl restart docker'
                    ]
                })
        
        for warning in self.warnings:
            if "дескрипторов" in warning:
                recommendations['warnings'].append({
                    'issue': warning,
                    'solution': 'Увеличить лимит файловых дескрипторов',
                    'commands': [
                        'echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf',
                        'echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf',
                        'sudo systemctl daemon-reload'
                    ]
                })
        
        # Добавляем ссылки на скрипты автоисправления
        recommendations['scripts'] = [
            {
                'name': 'port-conflict-fix.sh',
                'description': 'Автоматическое решение конфликтов портов',
                'url': 'https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/scripts/fixes/port-conflict-fix.sh'
            },
            {
                'name': 'increase-limits.sh', 
                'description': 'Увеличение системных лимитов',
                'url': 'https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/blob/main/code/monitoring-diagnostics/scripts/fixes/increase-limits.sh'
            }
        ]
        
        return recommendations


def main():
    """Главная функция"""
    print("🚀 Monitoring System Analyzer v1.0")
    print("📁 GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices")
    print("💬 Telegram: @DevOps_best_practices\n")
    
    analyzer = MonitoringAnalyzer()
    
    try:
        report = analyzer.analyze()
        
        # Вывод результатов
        summary = report['summary']
        print(f"\n{'='*50}")
        print(f"📊 Оценка готовности: {summary['readiness_score']}%")
        print(f"📋 Статус: {summary['message']}")
        print(f"❌ Критических проблем: {summary['critical_issues']}")
        print(f"⚠️ Предупреждений: {summary['warnings']}")
        print(f"{'='*50}")
        
        if analyzer.issues:
            print("\n❌ Критические проблемы:")
            for issue in analyzer.issues:
                print(f"  - {issue}")
                
        if analyzer.warnings:
            print("\n⚠️ Предупреждения:")
            for warning in analyzer.warnings:
                print(f"  - {warning}")
        
        if summary['readiness_score'] >= 80:
            print(f"\n✅ Система готова! Можно запускать мониторинг.")
        elif summary['readiness_score'] >= 60:
            print(f"\n⚠️ Система готова с оговорками. Рекомендуется устранить предупреждения.")
        else:
            print(f"\n❌ Система НЕ готова. Необходимо устранить критические проблемы.")
            
        # Сохранение отчета
        report_file = f'monitoring_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        print(f"\n📄 Полный отчет сохранен: {report_file}")
        print("🔧 Инструкции по исправлению: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/tree/main/code/monitoring-diagnostics")
        
        # Возвращаем код выхода в зависимости от готовности
        sys.exit(0 if summary['readiness_score'] >= 60 else 1)
        
    except KeyboardInterrupt:
        print("\n⛔ Анализ прерван пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Ошибка анализа: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()