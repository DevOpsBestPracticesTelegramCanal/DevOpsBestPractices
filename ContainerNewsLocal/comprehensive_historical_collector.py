#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Historical Container News Collector for last 3 months
Расширенный исторический сборщик новостей за последние 3 месяца
"""

import feedparser
import requests
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import hashlib
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/comprehensive_collector.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ComprehensiveHistoricalCollector:
    """Расширенный сборщик исторических новостей"""
    
    def __init__(self):
        self.db_path = Path("data/comprehensive_news.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Период сбора - последние 3 месяца
        now = datetime.now()
        self.start_date = now - timedelta(days=90)
        self.end_date = now
        
        logger.info(f"Период сбора: {self.start_date.strftime('%Y-%m-%d')} - {self.end_date.strftime('%Y-%m-%d')}")
        
        # Инициализация БД
        self.init_database()
        
        # Полная база источников
        self.sources = [
            # Официальные блоги
            {'name': 'Kubernetes Blog', 'url': 'https://kubernetes.io/feed.xml', 'category': 'kubernetes'},
            {'name': 'Kubernetes Developer', 'url': 'https://kubernetes.dev/feed.xml', 'category': 'kubernetes'},
            {'name': 'Docker Blog', 'url': 'https://www.docker.com/blog/feed', 'category': 'docker'},
            {'name': 'Podman Blog', 'url': 'https://podman.io/blog/feed', 'category': 'podman'},
            
            # GitHub релизы - основные
            {'name': 'Kubernetes Releases', 'url': 'https://github.com/kubernetes/kubernetes/releases.atom', 'category': 'releases'},
            {'name': 'Docker CE Releases', 'url': 'https://github.com/docker/docker-ce/releases.atom', 'category': 'releases'},
            {'name': 'Podman Releases', 'url': 'https://github.com/containers/podman/releases.atom', 'category': 'releases'},
            {'name': 'containerd Releases', 'url': 'https://github.com/containerd/containerd/releases.atom', 'category': 'releases'},
            {'name': 'CRI-O Releases', 'url': 'https://github.com/cri-o/cri-o/releases.atom', 'category': 'releases'},
            
            # Инструменты управления
            {'name': 'Helm Releases', 'url': 'https://github.com/helm/helm/releases.atom', 'category': 'tools'},
            {'name': 'K9s Releases', 'url': 'https://github.com/derailed/k9s/releases.atom', 'category': 'tools'},
            {'name': 'Lens Releases', 'url': 'https://github.com/lensapp/lens/releases.atom', 'category': 'tools'},
            {'name': 'Portainer Releases', 'url': 'https://github.com/portainer/portainer/releases.atom', 'category': 'tools'},
            
            # Мониторинг
            {'name': 'Prometheus Releases', 'url': 'https://github.com/prometheus/prometheus/releases.atom', 'category': 'monitoring'},
            {'name': 'Grafana Releases', 'url': 'https://github.com/grafana/grafana/releases.atom', 'category': 'monitoring'},
            {'name': 'Jaeger Releases', 'url': 'https://github.com/jaegertracing/jaeger/releases.atom', 'category': 'monitoring'},
            
            # Сети и безопасность
            {'name': 'Cilium Releases', 'url': 'https://github.com/cilium/cilium/releases.atom', 'category': 'networking'},
            {'name': 'Calico Releases', 'url': 'https://github.com/projectcalico/calico/releases.atom', 'category': 'networking'},
            {'name': 'Falco Releases', 'url': 'https://github.com/falcosecurity/falco/releases.atom', 'category': 'security'},
            {'name': 'Trivy Releases', 'url': 'https://github.com/aquasecurity/trivy/releases.atom', 'category': 'security'},
            {'name': 'OPA Releases', 'url': 'https://github.com/open-policy-agent/opa/releases.atom', 'category': 'security'},
            
            # CI/CD и GitOps
            {'name': 'Argo CD Releases', 'url': 'https://github.com/argoproj/argo-cd/releases.atom', 'category': 'gitops'},
            {'name': 'FluxCD Releases', 'url': 'https://github.com/fluxcd/flux/releases.atom', 'category': 'gitops'},
            {'name': 'Tekton Pipeline Releases', 'url': 'https://github.com/tektoncd/pipeline/releases.atom', 'category': 'gitops'},
            
            # Хранилище
            {'name': 'Rook Releases', 'url': 'https://github.com/rook/rook/releases.atom', 'category': 'storage'},
            {'name': 'MinIO Releases', 'url': 'https://github.com/minio/minio/releases.atom', 'category': 'storage'},
            
            # Dev.to источники
            {'name': 'Dev.to Docker', 'url': 'https://dev.to/feed/tag/docker', 'category': 'community'},
            {'name': 'Dev.to Kubernetes', 'url': 'https://dev.to/feed/tag/kubernetes', 'category': 'community'},
            {'name': 'Dev.to Containers', 'url': 'https://dev.to/feed/tag/container', 'category': 'community'},
            
            # Специализированные платформы  
            {'name': 'Medium learnk8s', 'url': 'https://medium.com/feed/learnk8s', 'category': 'education'},
            {'name': 'ITNEXT Kubernetes', 'url': 'https://itnext.io/feed/tagged/kubernetes', 'category': 'community'},
            {'name': 'The New Stack Kubernetes', 'url': 'https://thenewstack.io/kubernetes/feed', 'category': 'news'},
            {'name': 'Container Journal', 'url': 'https://containerjournal.com/feed', 'category': 'news'},
            
            # Облачные провайдеры
            {'name': 'Google Cloud Containers', 'url': 'https://cloud.google.com/blog/products/containers-kubernetes/rss', 'category': 'cloud'},
            {'name': 'AWS OpenSource', 'url': 'https://aws.amazon.com/blogs/opensource/feed/', 'category': 'cloud'},
            {'name': 'Azure Blog', 'url': 'https://azure.microsoft.com/en-us/blog/feed', 'category': 'cloud'},
            
            # Российские источники
            {'name': 'Yandex Cloud', 'url': 'https://cloud.yandex.ru/blog/rss', 'category': 'russian'},
            {'name': 'Selectel Blog', 'url': 'https://blog.selectel.ru/rss', 'category': 'russian'},
            
            # Вендорские блоги
            {'name': 'Rancher Blog', 'url': 'https://rancher.com/blog/rss.xml', 'category': 'vendor'},
            {'name': 'VMware Cloud Native', 'url': 'https://blog.vmware.com/cloudnative/feed', 'category': 'vendor'},
            {'name': 'HashiCorp Engineering', 'url': 'https://engineering.hashicorp.com/rss.xml', 'category': 'vendor'},
            
            # Безопасность
            {'name': 'AquaSec Blog', 'url': 'https://blog.aquasec.com/feed', 'category': 'security'},
            {'name': 'Sysdig Blog', 'url': 'https://blog.sysdig.com/feed', 'category': 'security'},
            
            # Дополнительные инструменты
            {'name': 'OpenEBS Blog', 'url': 'https://blog.openebs.io/feed', 'category': 'storage'},
            {'name': 'Crossplane Blog', 'url': 'https://blog.crossplane.io/feed', 'category': 'cloud'},
            {'name': 'Spinnaker Blog', 'url': 'https://blog.spinnaker.io/feed', 'category': 'deployment'},
        ]

    def init_database(self):
        """Инициализация БД"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS comprehensive_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    description TEXT,
                    category TEXT,
                    source TEXT,
                    published_date TEXT,
                    date_obj DATETIME,
                    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hash_id TEXT UNIQUE
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON comprehensive_news(date_obj)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_category ON comprehensive_news(category)')

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Улучшенный парсинг даты"""
        if not date_str:
            return None
        try:
            import time
            from email.utils import parsedate_tz
            
            # parsedate_tz из email.utils
            parsed = parsedate_tz(date_str)
            if parsed:
                timestamp = time.mktime(parsed[:9])
                return datetime.fromtimestamp(timestamp)
            
            # feedparser fallback
            parsed = feedparser._parse_date(date_str)
            if parsed:
                return datetime(*parsed[:6])
        except:
            pass
        return None

    def is_in_period(self, date: datetime) -> bool:
        """Проверка попадания в период"""
        if not date:
            return False
        return self.start_date <= date <= self.end_date

    def generate_hash_id(self, title: str, url: str) -> str:
        """Генерация уникального хэша"""
        content = f"{title}{url}"
        return hashlib.md5(content.encode()).hexdigest()

    def fetch_feed(self, url: str) -> Optional[feedparser.FeedParserDict]:
        """Получение RSS с улучшенной обработкой"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            return feedparser.parse(response.content)
        except Exception as e:
            logger.error(f"Ошибка при получении {url}: {e}")
            return None

    def collect_news(self):
        """Основной процесс сбора"""
        logger.info(f"Запуск сбора из {len(self.sources)} источников")
        
        stats = {
            'total': 0,
            'saved': 0,
            'by_category': {},
            'errors': 0
        }
        
        for i, source in enumerate(self.sources, 1):
            logger.info(f"[{i}/{len(self.sources)}] Обрабатываю: {source['name']}")
            
            feed = self.fetch_feed(source['url'])
            if not feed:
                stats['errors'] += 1
                continue
            
            found_count = 0
            
            for entry in feed.entries[:50]:  # Ограничиваем до 50 записей на источник
                try:
                    title = entry.get('title', 'No title')
                    url = entry.get('link', '')
                    description = entry.get('summary', entry.get('description', ''))
                    pub_date = self.parse_date(entry.get('published', ''))
                    
                    if not self.is_in_period(pub_date):
                        continue
                    
                    hash_id = self.generate_hash_id(title, url)
                    
                    # Сохранение с проверкой дубликатов
                    try:
                        with sqlite3.connect(self.db_path) as conn:
                            conn.execute('''
                                INSERT OR IGNORE INTO comprehensive_news 
                                (title, url, description, category, source, published_date, date_obj, hash_id)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                title, url, description, source['category'], 
                                source['name'], str(pub_date), pub_date, hash_id
                            ))
                            
                            if conn.total_changes > 0:
                                stats['saved'] += 1
                                found_count += 1
                                
                                category = source['category']
                                stats['by_category'][category] = stats['by_category'].get(category, 0) + 1
                    
                    except sqlite3.IntegrityError:
                        pass  # Дубликат
                    
                    stats['total'] += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки записи из {source['name']}: {e}")
            
            logger.info(f"  Найдено в период: {found_count}")
            time.sleep(1)  # Пауза между источниками
        
        # Итоги
        logger.info(f"\n=== ИТОГИ СБОРА ===")
        logger.info(f"Всего обработано: {stats['total']}")
        logger.info(f"Сохранено уникальных: {stats['saved']}")
        logger.info(f"Ошибок источников: {stats['errors']}")
        logger.info(f"По категориям:")
        for category, count in stats['by_category'].items():
            logger.info(f"  {category}: {count}")
        
        return stats

    def generate_report(self):
        """Генерация детального отчета"""
        with sqlite3.connect(self.db_path) as conn:
            # Общая статистика
            total_count = conn.execute("SELECT COUNT(*) FROM comprehensive_news").fetchone()[0]
            
            # По категориям
            categories = dict(conn.execute('''
                SELECT category, COUNT(*) 
                FROM comprehensive_news 
                GROUP BY category 
                ORDER BY COUNT(*) DESC
            ''').fetchall())
            
            # По месяцам
            monthly_stats = dict(conn.execute('''
                SELECT strftime('%Y-%m', date_obj) as month, COUNT(*) 
                FROM comprehensive_news 
                WHERE date_obj IS NOT NULL
                GROUP BY month 
                ORDER BY month DESC
            ''').fetchall())
            
            # Топ источники
            top_sources = dict(conn.execute('''
                SELECT source, COUNT(*) 
                FROM comprehensive_news 
                GROUP BY source 
                ORDER BY COUNT(*) DESC 
                LIMIT 10
            ''').fetchall())
            
            # Топ новости по категориям
            top_news = {}
            for category in categories.keys():
                news_list = conn.execute('''
                    SELECT title, url, source, published_date
                    FROM comprehensive_news 
                    WHERE category = ?
                    ORDER BY date_obj DESC
                    LIMIT 5
                ''', (category,)).fetchall()
                top_news[category] = [list(row) for row in news_list]
        
        # Формирование отчета
        report = {
            'period': {
                'start': self.start_date.strftime('%Y-%m-%d'),
                'end': self.end_date.strftime('%Y-%m-%d')
            },
            'total_news': total_count,
            'categories': categories,
            'monthly_distribution': monthly_stats,
            'top_sources': top_sources,
            'top_news_by_category': top_news,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Сохранение отчета
        output_file = f"data/comprehensive_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Детальный отчет сохранен: {output_file}")
        return output_file

def main():
    """Главная функция"""
    collector = ComprehensiveHistoricalCollector()
    
    try:
        # Сбор
        stats = collector.collect_news()
        
        # Отчет
        report_file = collector.generate_report()
        
        logger.info(f"Сбор завершен успешно!")
        logger.info(f"Отчет: {report_file}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        return 1

if __name__ == "__main__":
    exit(main())