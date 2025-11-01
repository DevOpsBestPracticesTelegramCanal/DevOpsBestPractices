#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historical Container Technologies News Collector for Aug, Sep, Oct 2025
Исторический сборщик новостей контейнерных технологий за август, сентябрь, октябрь 2025
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
import re
from dataclasses import dataclass, asdict

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/historical_3months_collector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class HistoricalNewsItem:
    """Структура исторической новости"""
    title: str
    url: str
    description: str
    category: str
    source: str
    published_date: datetime
    content_type: str
    importance: int
    hash_id: str
    tags: List[str]
    month: int  # 8, 9, 10

class HistoricalNewsCollector:
    """Сборщик исторических новостей за август-октябрь 2025"""
    
    def __init__(self, db_path: str = "data/historical_3months_news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Периоды для сбора
        self.target_months = [
            (2025, 8),   # Август 2025
            (2025, 9),   # Сентябрь 2025
            (2025, 10)   # Октябрь 2025
        ]
        
        # Инициализация БД
        self.init_database()
        
        # Загрузка источников
        self.sources = self.load_comprehensive_sources()
        
        logger.info(f"Инициализирован исторический сборщик для {len(self.target_months)} месяцев")

    def load_comprehensive_sources(self) -> List[Dict]:
        """Загрузка всех проверенных источников"""
        return [
            # === KUBERNETES ECOSYSTEM ===
            {
                'name': 'Kubernetes Official Blog',
                'url': 'https://kubernetes.io/feed.xml',
                'category': 'kubernetes',
                'importance': 5
            },
            {
                'name': 'Kubernetes Releases',
                'url': 'https://github.com/kubernetes/kubernetes/releases.atom',
                'category': 'kubernetes',
                'importance': 5
            },
            {
                'name': 'Minikube Releases',
                'url': 'https://github.com/kubernetes/minikube/releases.atom',
                'category': 'kubernetes',
                'importance': 3
            },
            {
                'name': 'KIND Releases',
                'url': 'https://github.com/kubernetes-sigs/kind/releases.atom',
                'category': 'kubernetes',
                'importance': 3
            },
            {
                'name': 'K3s Releases',
                'url': 'https://github.com/k3s-io/k3s/releases.atom',
                'category': 'kubernetes',
                'importance': 4
            },
            
            # === DOCKER ECOSYSTEM ===
            {
                'name': 'Docker Official Blog',
                'url': 'https://www.docker.com/blog/feed/',
                'category': 'docker',
                'importance': 5
            },
            {
                'name': 'Docker CE Releases',
                'url': 'https://github.com/docker/docker-ce/releases.atom',
                'category': 'docker',
                'importance': 5
            },
            {
                'name': 'Docker CLI Releases',
                'url': 'https://github.com/docker/cli/releases.atom',
                'category': 'docker',
                'importance': 4
            },
            {
                'name': 'Docker Compose Releases',
                'url': 'https://github.com/docker/compose/releases.atom',
                'category': 'docker',
                'importance': 4
            },
            
            # === PODMAN ECOSYSTEM ===
            {
                'name': 'Podman Releases',
                'url': 'https://github.com/containers/podman/releases.atom',
                'category': 'podman',
                'importance': 5
            },
            {
                'name': 'Buildah Releases',
                'url': 'https://github.com/containers/buildah/releases.atom',
                'category': 'podman',
                'importance': 3
            },
            {
                'name': 'Skopeo Releases',
                'url': 'https://github.com/containers/skopeo/releases.atom',
                'category': 'podman',
                'importance': 3
            },
            
            # === CONTAINER RUNTIME ===
            {
                'name': 'containerd Releases',
                'url': 'https://github.com/containerd/containerd/releases.atom',
                'category': 'runtime',
                'importance': 4
            },
            {
                'name': 'CRI-O Releases',
                'url': 'https://github.com/cri-o/cri-o/releases.atom',
                'category': 'runtime',
                'importance': 3
            },
            {
                'name': 'runc Releases',
                'url': 'https://github.com/opencontainers/runc/releases.atom',
                'category': 'runtime',
                'importance': 3
            },
            
            # === OBSERVABILITY ===
            {
                'name': 'Prometheus Releases',
                'url': 'https://github.com/prometheus/prometheus/releases.atom',
                'category': 'monitoring',
                'importance': 5
            },
            {
                'name': 'Grafana Releases',
                'url': 'https://github.com/grafana/grafana/releases.atom',
                'category': 'monitoring',
                'importance': 5
            },
            {
                'name': 'Jaeger Releases',
                'url': 'https://github.com/jaegertracing/jaeger/releases.atom',
                'category': 'monitoring',
                'importance': 4
            },
            
            # === SERVICE MESH ===
            {
                'name': 'Istio Releases',
                'url': 'https://github.com/istio/istio/releases.atom',
                'category': 'service_mesh',
                'importance': 5
            },
            {
                'name': 'Linkerd Releases',
                'url': 'https://github.com/linkerd/linkerd2/releases.atom',
                'category': 'service_mesh',
                'importance': 4
            },
            {
                'name': 'Cilium Releases',
                'url': 'https://github.com/cilium/cilium/releases.atom',
                'category': 'networking',
                'importance': 4
            },
            
            # === SECURITY ===
            {
                'name': 'Falco Releases',
                'url': 'https://github.com/falcosecurity/falco/releases.atom',
                'category': 'security',
                'importance': 4
            },
            {
                'name': 'Trivy Releases',
                'url': 'https://github.com/aquasecurity/trivy/releases.atom',
                'category': 'security',
                'importance': 4
            },
            {
                'name': 'Open Policy Agent',
                'url': 'https://github.com/open-policy-agent/opa/releases.atom',
                'category': 'security',
                'importance': 4
            },
            
            # === GITOPS & CI/CD ===
            {
                'name': 'ArgoCD Releases',
                'url': 'https://github.com/argoproj/argo-cd/releases.atom',
                'category': 'gitops',
                'importance': 5
            },
            {
                'name': 'Helm Releases',
                'url': 'https://github.com/helm/helm/releases.atom',
                'category': 'gitops',
                'importance': 4
            },
            {
                'name': 'Tekton Pipeline',
                'url': 'https://github.com/tektoncd/pipeline/releases.atom',
                'category': 'cicd',
                'importance': 3
            },
            
            # === CLOUD PROVIDERS ===
            {
                'name': 'AWS Containers Blog',
                'url': 'https://aws.amazon.com/blogs/containers/feed/',
                'category': 'cloud',
                'importance': 5
            },
            {
                'name': 'Google Cloud Containers',
                'url': 'https://cloud.google.com/blog/products/containers-kubernetes/rss',
                'category': 'cloud',
                'importance': 5
            },
            
            # === COMMUNITY ===
            {
                'name': 'Dev.to Docker',
                'url': 'https://dev.to/feed/tag/docker',
                'category': 'community',
                'importance': 3
            },
            {
                'name': 'Dev.to Kubernetes',
                'url': 'https://dev.to/feed/tag/kubernetes',
                'category': 'community',
                'importance': 3
            },
            {
                'name': 'Dev.to Containers',
                'url': 'https://dev.to/feed/tag/container',
                'category': 'community',
                'importance': 3
            }
        ]

    def init_database(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS historical_news_3months (
                    hash_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    description TEXT,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_date TIMESTAMP,
                    content_type TEXT NOT NULL,
                    importance INTEGER,
                    tags TEXT,
                    month INTEGER,
                    year INTEGER,
                    collected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_historical_month_year 
                ON historical_news_3months(year, month)
            ''')

    def fetch_rss_safely(self, url: str, timeout: int = 30) -> Optional[feedparser.FeedParserDict]:
        """Безопасное получение RSS с обработкой ошибок"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if hasattr(feed, 'bozo') and feed.bozo:
                logger.warning(f"RSS feed может быть некорректным: {url}")
            
            return feed
            
        except requests.RequestException as e:
            logger.error(f"Ошибка сети при запросе {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при обработке {url}: {e}")
            return None

    def parse_date_safely(self, date_str: str) -> Optional[datetime]:
        """Безопасный парсинг даты"""
        if not date_str:
            return None
        
        try:
            # Попытка парсинга через feedparser
            parsed_date = feedparser._parse_date(date_str)
            if parsed_date:
                return datetime(*parsed_date[:6])
        except:
            pass
        
        return None

    def is_target_month(self, date: datetime) -> bool:
        """Проверка, попадает ли дата в целевые месяцы"""
        if not date:
            return False
        
        return (date.year, date.month) in self.target_months

    def classify_content_type(self, title: str, description: str) -> str:
        """Классификация типа контента"""
        text = (title + " " + description).lower()
        
        if any(keyword in text for keyword in ['release', 'released', 'version', 'v1.', 'v2.', 'v3.']):
            return 'releases'
        elif any(keyword in text for keyword in ['security', 'vulnerability', 'cve-', 'patch', 'fix']):
            return 'security'
        elif any(keyword in text for keyword in ['production', 'enterprise', 'stable', 'ga']):
            return 'production_ready'
        elif any(keyword in text for keyword in ['best practice', 'guide', 'tutorial', 'how to']):
            return 'best_practices'
        elif any(keyword in text for keyword in ['trend', 'future', 'innovation', 'new']):
            return 'trends'
        
        return 'general'

    def extract_tags(self, title: str, description: str, category: str) -> List[str]:
        """Извлечение тегов"""
        text = (title + " " + description).lower()
        tags = [category]
        
        tech_keywords = {
            'microservices': 'microservices',
            'serverless': 'serverless',
            'ai': 'ai-ml',
            'machine learning': 'ai-ml',
            'edge': 'edge-computing',
            'devsecops': 'devsecops',
            'multicloud': 'multicloud'
        }
        
        for keyword, tag in tech_keywords.items():
            if keyword in text:
                tags.append(tag)
        
        return list(set(tags))

    def collect_historical_news(self) -> Dict[str, int]:
        """Сбор исторических новостей за 3 месяца"""
        logger.info("🚀 Запуск сбора исторических новостей за август-октябрь 2025")
        
        stats = {
            'total_processed': 0,
            'relevant_items': 0,
            'saved_items': 0,
            'errors': 0,
            'by_month': {8: 0, 9: 0, 10: 0}
        }
        
        for i, source in enumerate(self.sources, 1):
            try:
                logger.info(f"🔄 [{i}/{len(self.sources)}] Обработка: {source['name']}")
                
                feed = self.fetch_rss_safely(source['url'])
                if not feed:
                    stats['errors'] += 1
                    continue
                
                entries_processed = 0
                
                # Обрабатываем больше записей для исторического сбора
                for entry in feed.entries[:100]:
                    try:
                        title = entry.get('title', 'No title')
                        url = entry.get('link', '')
                        description = entry.get('summary', entry.get('description', ''))
                        published_date = self.parse_date_safely(entry.get('published', ''))
                        
                        # Проверяем, попадает ли в целевые месяцы
                        if not self.is_target_month(published_date):
                            continue
                        
                        stats['relevant_items'] += 1
                        
                        # Создание хеша
                        hash_id = hashlib.md5(f"{title}{url}".encode()).hexdigest()
                        
                        # Классификация
                        content_type = self.classify_content_type(title, description)
                        tags = self.extract_tags(title, description, source['category'])
                        
                        # Создание объекта новости
                        news_item = HistoricalNewsItem(
                            title=title,
                            url=url,
                            description=description,
                            category=source['category'],
                            source=source['name'],
                            published_date=published_date,
                            content_type=content_type,
                            importance=source['importance'],
                            hash_id=hash_id,
                            tags=tags,
                            month=published_date.month
                        )
                        
                        # Сохранение
                        if self.save_news_item(news_item):
                            stats['saved_items'] += 1
                            stats['by_month'][published_date.month] += 1
                            entries_processed += 1
                        
                        stats['total_processed'] += 1
                        
                    except Exception as e:
                        logger.error(f"Ошибка при обработке записи: {e}")
                        stats['errors'] += 1
                
                logger.info(f"✅ {source['name']}: найдено {entries_processed} релевантных новостей")
                
                # Пауза между источниками
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Ошибка при обработке источника {source['name']}: {e}")
                stats['errors'] += 1
        
        logger.info(f"🎯 Сбор завершен:")
        logger.info(f"   📊 Всего обработано: {stats['total_processed']}")
        logger.info(f"   ✅ Релевантных новостей: {stats['relevant_items']}")
        logger.info(f"   💾 Сохранено: {stats['saved_items']}")
        logger.info(f"   📅 По месяцам: Авг={stats['by_month'][8]}, Сен={stats['by_month'][9]}, Окт={stats['by_month'][10]}")
        
        return stats

    def save_news_item(self, news_item: HistoricalNewsItem) -> bool:
        """Сохранение новости в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO historical_news_3months 
                    (hash_id, title, url, description, category, source, 
                     published_date, content_type, importance, tags, month, year)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    news_item.hash_id,
                    news_item.title,
                    news_item.url,
                    news_item.description,
                    news_item.category,
                    news_item.source,
                    news_item.published_date,
                    news_item.content_type,
                    news_item.importance,
                    json.dumps(news_item.tags),
                    news_item.month,
                    2025
                ))
                
                return conn.total_changes > 0
                
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Ошибка при сохранении: {e}")
            return False

    def generate_monthly_reports(self) -> Dict:
        """Генерация отчетов по месяцам"""
        reports = {}
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            for year, month in self.target_months:
                month_name = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                             'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'][month]
                
                # Общая статистика
                total = conn.execute(
                    "SELECT COUNT(*) as count FROM historical_news_3months WHERE year=? AND month=?",
                    (year, month)
                ).fetchone()['count']
                
                # По категориям
                categories = dict(conn.execute('''
                    SELECT category, COUNT(*) as count 
                    FROM historical_news_3months 
                    WHERE year=? AND month=?
                    GROUP BY category 
                    ORDER BY count DESC
                ''', (year, month)).fetchall())
                
                # По типу контента
                content_types = dict(conn.execute('''
                    SELECT content_type, COUNT(*) as count 
                    FROM historical_news_3months 
                    WHERE year=? AND month=?
                    GROUP BY content_type 
                    ORDER BY count DESC
                ''', (year, month)).fetchall())
                
                # Топ новости
                top_news = conn.execute('''
                    SELECT title, url, category, importance, source
                    FROM historical_news_3months 
                    WHERE year=? AND month=?
                    ORDER BY importance DESC, published_date DESC
                    LIMIT 5
                ''', (year, month)).fetchall()
                
                reports[f"{year}-{month:02d}"] = {
                    'month_name': month_name,
                    'year': year,
                    'month': month,
                    'total_news': total,
                    'categories': categories,
                    'content_types': content_types,
                    'top_news': [dict(row) for row in top_news]
                }
        
        return reports

    def export_results(self) -> str:
        """Экспорт результатов"""
        reports = self.generate_monthly_reports()
        
        output_file = f"data/historical_3months_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📊 Отчеты экспортированы: {output_file}")
        return output_file

def main():
    """Основная функция"""
    collector = HistoricalNewsCollector()
    
    try:
        # Сбор новостей
        stats = collector.collect_historical_news()
        
        # Экспорт результатов
        output_file = collector.export_results()
        
        print("\n" + "="*60)
        print("🎯 ИТОГОВАЯ СТАТИСТИКА СБОРА")
        print("="*60)
        print(f"📊 Всего обработано записей: {stats['total_processed']}")
        print(f"✅ Релевантных новостей: {stats['relevant_items']}")
        print(f"💾 Сохранено в БД: {stats['saved_items']}")
        print(f"❌ Ошибок: {stats['errors']}")
        print("\n📅 Распределение по месяцам:")
        print(f"   🗓️  Август 2025: {stats['by_month'][8]} новостей")
        print(f"   🗓️  Сентябрь 2025: {stats['by_month'][9]} новостей")
        print(f"   🗓️  Октябрь 2025: {stats['by_month'][10]} новостей")
        print(f"\n📋 Отчет сохранен: {output_file}")
        print("="*60)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        return 1

if __name__ == "__main__":
    exit(main())