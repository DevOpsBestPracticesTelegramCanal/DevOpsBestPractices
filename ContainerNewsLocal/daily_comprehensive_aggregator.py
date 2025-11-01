#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Comprehensive Container Technologies News Aggregator
Ежедневный комплексный агрегатор новостей контейнерных технологий

Покрывает все аспекты: тренды, best practices, production-ready решения
Источники: проверенные RSS из PDF + дополнительные верифицированные
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
        logging.FileHandler('data/daily_aggregator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class NewsItem:
    """Структура новости"""
    title: str
    url: str
    description: str
    category: str
    source: str
    published_date: datetime
    content_type: str  # trends, best_practices, production_ready, releases, security
    importance: int  # 1-5
    hash_id: str
    tags: List[str]

class DailyContainerNewsAggregator:
    """Ежедневный агрегатор новостей контейнерных технологий"""
    
    def __init__(self, db_path: str = "data/daily_container_news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Инициализация БД
        self.init_database()
        
        # Загрузка источников
        self.sources = self.load_comprehensive_sources()
        
        logger.info(f"Инициализирован агрегатор с {len(self.sources)} источниками")

    def load_comprehensive_sources(self) -> Dict[str, List[Dict]]:
        """Загрузка всех проверенных источников из PDF + дополнительные"""
        return {
            # === OFFICIAL KUBERNETES ECOSYSTEM ===
            'kubernetes_official': [
                {
                    'name': 'Kubernetes Official Blog',
                    'url': 'https://kubernetes.io/feed.xml',
                    'category': 'kubernetes',
                    'content_types': ['trends', 'best_practices', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Kubernetes Releases',
                    'url': 'https://github.com/kubernetes/kubernetes/releases.atom',
                    'category': 'kubernetes',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Minikube Releases',
                    'url': 'https://github.com/kubernetes/minikube/releases.atom',
                    'category': 'kubernetes',
                    'content_types': ['releases'],
                    'importance': 3
                },
                {
                    'name': 'KIND Releases',
                    'url': 'https://github.com/kubernetes-sigs/kind/releases.atom',
                    'category': 'kubernetes',
                    'content_types': ['releases'],
                    'importance': 3
                },
                {
                    'name': 'K3s Releases',
                    'url': 'https://github.com/k3s-io/k3s/releases.atom',
                    'category': 'kubernetes',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                },
                {
                    'name': 'K0s Releases',
                    'url': 'https://github.com/k0sproject/k0s/releases.atom',
                    'category': 'kubernetes',
                    'content_types': ['releases'],
                    'importance': 3
                }
            ],
            
            # === DOCKER ECOSYSTEM ===
            'docker_official': [
                {
                    'name': 'Docker Official Blog',
                    'url': 'https://www.docker.com/blog/feed/',
                    'category': 'docker',
                    'content_types': ['trends', 'best_practices', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Docker CE Releases',
                    'url': 'https://github.com/docker/docker-ce/releases.atom',
                    'category': 'docker',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Docker CLI Releases',
                    'url': 'https://github.com/docker/cli/releases.atom',
                    'category': 'docker',
                    'content_types': ['releases'],
                    'importance': 4
                },
                {
                    'name': 'Docker Compose Releases',
                    'url': 'https://github.com/docker/compose/releases.atom',
                    'category': 'docker',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                }
            ],
            
            # === PODMAN & RED HAT ECOSYSTEM ===
            'podman_ecosystem': [
                {
                    'name': 'Podman Releases',
                    'url': 'https://github.com/containers/podman/releases.atom',
                    'category': 'podman',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Buildah Releases',
                    'url': 'https://github.com/containers/buildah/releases.atom',
                    'category': 'podman',
                    'content_types': ['releases'],
                    'importance': 3
                },
                {
                    'name': 'Skopeo Releases',
                    'url': 'https://github.com/containers/skopeo/releases.atom',
                    'category': 'podman',
                    'content_types': ['releases'],
                    'importance': 3
                }
            ],
            
            # === CONTAINER RUNTIME & OCI ===
            'container_runtime': [
                {
                    'name': 'containerd Releases',
                    'url': 'https://github.com/containerd/containerd/releases.atom',
                    'category': 'runtime',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                },
                {
                    'name': 'CRI-O Releases',
                    'url': 'https://github.com/cri-o/cri-o/releases.atom',
                    'category': 'runtime',
                    'content_types': ['releases'],
                    'importance': 3
                },
                {
                    'name': 'runc Releases',
                    'url': 'https://github.com/opencontainers/runc/releases.atom',
                    'category': 'runtime',
                    'content_types': ['releases'],
                    'importance': 3
                }
            ],
            
            # === OBSERVABILITY STACK ===
            'observability': [
                {
                    'name': 'Prometheus Releases',
                    'url': 'https://github.com/prometheus/prometheus/releases.atom',
                    'category': 'monitoring',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Grafana Releases',
                    'url': 'https://github.com/grafana/grafana/releases.atom',
                    'category': 'monitoring',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Jaeger Releases',
                    'url': 'https://github.com/jaegertracing/jaeger/releases.atom',
                    'category': 'monitoring',
                    'content_types': ['releases'],
                    'importance': 4
                },
                {
                    'name': 'OpenTelemetry Collector',
                    'url': 'https://github.com/open-telemetry/opentelemetry-collector/releases.atom',
                    'category': 'monitoring',
                    'content_types': ['releases'],
                    'importance': 4
                }
            ],
            
            # === SERVICE MESH ===
            'service_mesh': [
                {
                    'name': 'Istio Releases',
                    'url': 'https://github.com/istio/istio/releases.atom',
                    'category': 'service_mesh',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Linkerd Releases',
                    'url': 'https://github.com/linkerd/linkerd2/releases.atom',
                    'category': 'service_mesh',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                },
                {
                    'name': 'Cilium Releases',
                    'url': 'https://github.com/cilium/cilium/releases.atom',
                    'category': 'networking',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                }
            ],
            
            # === SECURITY ===
            'security': [
                {
                    'name': 'Falco Releases',
                    'url': 'https://github.com/falcosecurity/falco/releases.atom',
                    'category': 'security',
                    'content_types': ['releases', 'security'],
                    'importance': 4
                },
                {
                    'name': 'Trivy Releases',
                    'url': 'https://github.com/aquasecurity/trivy/releases.atom',
                    'category': 'security',
                    'content_types': ['releases', 'security'],
                    'importance': 4
                },
                {
                    'name': 'Open Policy Agent',
                    'url': 'https://github.com/open-policy-agent/opa/releases.atom',
                    'category': 'security',
                    'content_types': ['releases', 'security'],
                    'importance': 4
                }
            ],
            
            # === GITOPS & CI/CD ===
            'gitops_cicd': [
                {
                    'name': 'ArgoCD Releases',
                    'url': 'https://github.com/argoproj/argo-cd/releases.atom',
                    'category': 'gitops',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 5
                },
                {
                    'name': 'Flux CD Releases',
                    'url': 'https://github.com/fluxcd/flux2/releases.atom',
                    'category': 'gitops',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                },
                {
                    'name': 'Tekton Pipeline',
                    'url': 'https://github.com/tektoncd/pipeline/releases.atom',
                    'category': 'cicd',
                    'content_types': ['releases'],
                    'importance': 3
                },
                {
                    'name': 'Helm Releases',
                    'url': 'https://github.com/helm/helm/releases.atom',
                    'category': 'gitops',
                    'content_types': ['releases', 'production_ready'],
                    'importance': 4
                }
            ],
            
            # === WEBASSEMBLY & EDGE ===
            'webassembly_edge': [
                {
                    'name': 'WasmEdge Releases',
                    'url': 'https://github.com/WasmEdge/WasmEdge/releases.atom',
                    'category': 'webassembly',
                    'content_types': ['releases', 'trends'],
                    'importance': 3
                },
                {
                    'name': 'Wasmtime Releases',
                    'url': 'https://github.com/bytecodealliance/wasmtime/releases.atom',
                    'category': 'webassembly',
                    'content_types': ['releases'],
                    'importance': 3
                }
            ],
            
            # === CLOUD PROVIDERS ===
            'cloud_providers': [
                {
                    'name': 'AWS Containers Blog',
                    'url': 'https://aws.amazon.com/blogs/containers/feed/',
                    'category': 'cloud',
                    'content_types': ['best_practices', 'production_ready', 'trends'],
                    'importance': 5
                },
                {
                    'name': 'Google Cloud Containers',
                    'url': 'https://cloud.google.com/blog/products/containers-kubernetes/rss',
                    'category': 'cloud',
                    'content_types': ['best_practices', 'production_ready', 'trends'],
                    'importance': 5
                }
            ],
            
            # === COMMUNITY & AGGREGATORS ===
            'community': [
                {
                    'name': 'Dev.to Docker',
                    'url': 'https://dev.to/feed/tag/docker',
                    'category': 'community',
                    'content_types': ['trends', 'best_practices'],
                    'importance': 3
                },
                {
                    'name': 'Dev.to Kubernetes',
                    'url': 'https://dev.to/feed/tag/kubernetes',
                    'category': 'community',
                    'content_types': ['trends', 'best_practices'],
                    'importance': 3
                },
                {
                    'name': 'InfoQ DevOps',
                    'url': 'https://www.infoq.com/feed',
                    'category': 'community',
                    'content_types': ['trends', 'best_practices', 'production_ready'],
                    'importance': 4
                },
                {
                    'name': 'The New Stack',
                    'url': 'https://thenewstack.io/kubernetes/feed/',
                    'category': 'community',
                    'content_types': ['trends', 'best_practices'],
                    'importance': 4
                }
            ]
        }

    def init_database(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_news (
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
                    collected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed BOOLEAN DEFAULT FALSE
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_news_date 
                ON daily_news(published_date)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_news_category 
                ON daily_news(category)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_daily_news_content_type 
                ON daily_news(content_type)
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

    def parse_date_safely(self, date_str: str) -> datetime:
        """Безопасный парсинг даты"""
        if not date_str:
            return datetime.now()
        
        try:
            # Попытка парсинга через feedparser
            parsed_date = feedparser._parse_date(date_str)
            if parsed_date:
                return datetime(*parsed_date[:6])
        except:
            pass
        
        # Fallback на текущую дату
        return datetime.now()

    def classify_content_type(self, title: str, description: str) -> str:
        """Классификация типа контента"""
        text = (title + " " + description).lower()
        
        # Релизы
        if any(keyword in text for keyword in ['release', 'released', 'version', 'v1.', 'v2.', 'v3.']):
            return 'releases'
        
        # Безопасность
        if any(keyword in text for keyword in ['security', 'vulnerability', 'cve-', 'patch', 'fix']):
            return 'security'
        
        # Production-ready
        if any(keyword in text for keyword in ['production', 'enterprise', 'stable', 'ga', 'generally available']):
            return 'production_ready'
        
        # Best practices
        if any(keyword in text for keyword in ['best practice', 'guide', 'tutorial', 'how to', 'optimization']):
            return 'best_practices'
        
        # Тренды
        if any(keyword in text for keyword in ['trend', 'future', 'innovation', 'new', 'announcement']):
            return 'trends'
        
        return 'general'

    def extract_tags(self, title: str, description: str, category: str) -> List[str]:
        """Извлечение тегов из контента"""
        text = (title + " " + description).lower()
        tags = [category]
        
        # Технологические теги
        tech_keywords = {
            'microservices': 'microservices',
            'serverless': 'serverless',
            'ai': 'ai-ml',
            'machine learning': 'ai-ml',
            'edge': 'edge-computing',
            'iot': 'iot',
            'devsecops': 'devsecops',
            'finops': 'finops',
            'multicloud': 'multicloud',
            'hybrid': 'hybrid-cloud'
        }
        
        for keyword, tag in tech_keywords.items():
            if keyword in text:
                tags.append(tag)
        
        return list(set(tags))

    def calculate_importance(self, source_importance: int, content_type: str, title: str) -> int:
        """Расчет важности новости"""
        importance = source_importance
        
        # Корректировка по типу контента
        type_modifiers = {
            'security': +1,
            'production_ready': +1,
            'releases': 0,
            'best_practices': 0,
            'trends': -1
        }
        
        importance += type_modifiers.get(content_type, 0)
        
        # Корректировка по ключевым словам в заголовке
        title_lower = title.lower()
        if any(word in title_lower for word in ['critical', 'urgent', 'breaking']):
            importance += 1
        
        return max(1, min(5, importance))

    def collect_daily_news(self) -> Dict[str, int]:
        """Ежедневный сбор новостей"""
        logger.info("🚀 Запуск ежедневного сбора новостей")
        
        stats = {
            'total_processed': 0,
            'new_items': 0,
            'errors': 0
        }
        
        for category, sources in self.sources.items():
            logger.info(f"📂 Обработка категории: {category}")
            
            for source in sources:
                try:
                    logger.info(f"🔄 Обработка источника: {source['name']}")
                    
                    feed = self.fetch_rss_safely(source['url'])
                    if not feed:
                        stats['errors'] += 1
                        continue
                    
                    entries_processed = 0
                    
                    for entry in feed.entries[:20]:  # Ограничение на 20 последних новостей
                        try:
                            # Парсинг данных
                            title = entry.get('title', 'No title')
                            url = entry.get('link', '')
                            description = entry.get('summary', entry.get('description', ''))
                            published_date = self.parse_date_safely(entry.get('published', ''))
                            
                            # Пропуск старых новостей (старше 7 дней)
                            if published_date < datetime.now() - timedelta(days=7):
                                continue
                            
                            # Создание хеша для дедупликации
                            hash_id = hashlib.md5(f"{title}{url}".encode()).hexdigest()
                            
                            # Классификация
                            content_type = self.classify_content_type(title, description)
                            tags = self.extract_tags(title, description, source['category'])
                            importance = self.calculate_importance(source['importance'], content_type, title)
                            
                            # Создание объекта новости
                            news_item = NewsItem(
                                title=title,
                                url=url,
                                description=description,
                                category=source['category'],
                                source=source['name'],
                                published_date=published_date,
                                content_type=content_type,
                                importance=importance,
                                hash_id=hash_id,
                                tags=tags
                            )
                            
                            # Сохранение в БД
                            if self.save_news_item(news_item):
                                stats['new_items'] += 1
                                entries_processed += 1
                            
                            stats['total_processed'] += 1
                            
                        except Exception as e:
                            logger.error(f"Ошибка при обработке записи из {source['name']}: {e}")
                            stats['errors'] += 1
                    
                    logger.info(f"✅ {source['name']}: обработано {entries_processed} новых записей")
                    
                    # Пауза между источниками
                    time.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Ошибка при обработке источника {source['name']}: {e}")
                    stats['errors'] += 1
        
        logger.info(f"🎯 Сбор завершен: {stats['new_items']} новых новостей из {stats['total_processed']} обработанных")
        
        return stats

    def save_news_item(self, news_item: NewsItem) -> bool:
        """Сохранение новости в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO daily_news 
                    (hash_id, title, url, description, category, source, 
                     published_date, content_type, importance, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(news_item.tags)
                ))
                
                return conn.total_changes > 0
                
        except sqlite3.IntegrityError:
            return False  # Дубликат
        except Exception as e:
            logger.error(f"Ошибка при сохранении новости: {e}")
            return False

    def generate_daily_report(self) -> Dict:
        """Генерация ежедневного отчета"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Общая статистика
            total_news = conn.execute(
                "SELECT COUNT(*) as count FROM daily_news WHERE date(collected_date) = date('now')"
            ).fetchone()['count']
            
            # По категориям
            category_stats = dict(conn.execute('''
                SELECT category, COUNT(*) as count 
                FROM daily_news 
                WHERE date(collected_date) = date('now')
                GROUP BY category 
                ORDER BY count DESC
            ''').fetchall())
            
            # По типу контента
            content_type_stats = dict(conn.execute('''
                SELECT content_type, COUNT(*) as count 
                FROM daily_news 
                WHERE date(collected_date) = date('now')
                GROUP BY content_type 
                ORDER BY count DESC
            ''').fetchall())
            
            # Топ новости по важности
            top_news = conn.execute('''
                SELECT title, url, category, importance, source
                FROM daily_news 
                WHERE date(collected_date) = date('now')
                ORDER BY importance DESC, published_date DESC
                LIMIT 10
            ''').fetchall()
            
            return {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'total_news': total_news,
                'category_distribution': category_stats,
                'content_type_distribution': content_type_stats,
                'top_news': [dict(row) for row in top_news],
                'generated_at': datetime.now().isoformat()
            }

    def export_daily_summary(self, output_file: str = None) -> str:
        """Экспорт ежедневной сводки"""
        report = self.generate_daily_report()
        
        if not output_file:
            output_file = f"data/daily_summary_{datetime.now().strftime('%Y%m%d')}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📊 Ежедневная сводка экспортирована: {output_file}")
        return output_file

def main():
    """Основная функция для ежедневного запуска"""
    aggregator = DailyContainerNewsAggregator()
    
    try:
        # Сбор новостей
        stats = aggregator.collect_daily_news()
        
        # Генерация отчета
        aggregator.export_daily_summary()
        
        logger.info(f"✅ Ежедневный сбор завершен: {stats['new_items']} новых новостей")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении ежедневного сбора: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())