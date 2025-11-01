#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Historical Container News Collector for Aug, Sep, Oct 2025
Простой исторический сборщик новостей за август-октябрь 2025
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

# Настройка логирования без emoji
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/simple_historical.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SimpleHistoricalCollector:
    """Простой сборщик исторических новостей"""
    
    def __init__(self):
        self.db_path = Path("data/simple_historical_news.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Целевые месяцы - актуальные данные 2025
        self.target_months = [(2025, 8), (2025, 9), (2025, 10)]
        
        # Инициализация БД
        self.init_database()
        
        # Источники новостей
        self.sources = [
            {
                'name': 'Kubernetes Blog',
                'url': 'https://kubernetes.io/feed.xml',
                'category': 'kubernetes'
            },
            {
                'name': 'Docker Blog',
                'url': 'https://www.docker.com/blog/feed/',
                'category': 'docker'
            },
            {
                'name': 'Dev.to Docker',
                'url': 'https://dev.to/feed/tag/docker',
                'category': 'community'
            },
            {
                'name': 'Dev.to Kubernetes',
                'url': 'https://dev.to/feed/tag/kubernetes',
                'category': 'community'
            },
            {
                'name': 'Prometheus Releases',
                'url': 'https://github.com/prometheus/prometheus/releases.atom',
                'category': 'monitoring'
            },
            {
                'name': 'Grafana Releases',
                'url': 'https://github.com/grafana/grafana/releases.atom',
                'category': 'monitoring'
            }
        ]

    def init_database(self):
        """Инициализация БД"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS simple_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    description TEXT,
                    category TEXT,
                    source TEXT,
                    published_date TEXT,
                    month INTEGER,
                    year INTEGER,
                    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def fetch_feed(self, url: str) -> Optional[feedparser.FeedParserDict]:
        """Получение RSS"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            return feedparser.parse(response.content)
        except Exception as e:
            logger.error(f"Ошибка при получении {url}: {e}")
            return None

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Парсинг даты"""
        if not date_str:
            return None
        try:
            # Используем встроенную функцию feedparser для парсинга
            import time
            from email.utils import parsedate_tz
            
            # Сначала пробуем parsedate_tz из email.utils
            parsed = parsedate_tz(date_str)
            if parsed:
                timestamp = time.mktime(parsed[:9])
                return datetime.fromtimestamp(timestamp)
            
            # Если не получилось, пробуем feedparser
            parsed = feedparser._parse_date(date_str)
            if parsed:
                return datetime(*parsed[:6])
        except:
            pass
        return None

    def is_target_period(self, date: datetime) -> bool:
        """Проверка периода"""
        if not date:
            return False
        return (date.year, date.month) in self.target_months

    def collect_news(self):
        """Сбор новостей"""
        print("Запуск сбора новостей за август-октябрь 2025")
        
        stats = {'total': 0, 'saved': 0, 'by_month': {8: 0, 9: 0, 10: 0}}
        
        for i, source in enumerate(self.sources, 1):
            print(f"[{i}/{len(self.sources)}] Обработка: {source['name']}")
            
            feed = self.fetch_feed(source['url'])
            if not feed:
                continue
                
            found_count = 0
            
            for entry in feed.entries[:50]:
                try:
                    title = entry.get('title', 'No title')
                    url = entry.get('link', '')
                    description = entry.get('summary', entry.get('description', ''))
                    pub_date = self.parse_date(entry.get('published', ''))
                    
                    if not self.is_target_period(pub_date):
                        continue
                    
                    # Сохранение
                    try:
                        with sqlite3.connect(self.db_path) as conn:
                            conn.execute('''
                                INSERT OR IGNORE INTO simple_news 
                                (title, url, description, category, source, published_date, month, year)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                title, url, description, source['category'], 
                                source['name'], str(pub_date), pub_date.month, pub_date.year
                            ))
                            
                            if conn.total_changes > 0:
                                stats['saved'] += 1
                                stats['by_month'][pub_date.month] += 1
                                found_count += 1
                    
                    except sqlite3.IntegrityError:
                        pass  # Дубликат
                    
                    stats['total'] += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки записи: {e}")
            
            print(f"  Найдено: {found_count} релевантных новостей")
            time.sleep(1)
        
        print(f"\nИтоги сбора:")
        print(f"Всего обработано: {stats['total']}")
        print(f"Сохранено: {stats['saved']}")
        print(f"Август: {stats['by_month'][8]}")
        print(f"Сентябрь: {stats['by_month'][9]}")
        print(f"Октябрь: {stats['by_month'][10]}")
        
        return stats

    def generate_report(self):
        """Генерация отчета"""
        with sqlite3.connect(self.db_path) as conn:
            # Статистика по месяцам
            months_data = {}
            
            for year, month in self.target_months:
                month_name = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][month]
                
                count = conn.execute(
                    "SELECT COUNT(*) FROM simple_news WHERE year=? AND month=?",
                    (year, month)
                ).fetchone()[0]
                
                categories = dict(conn.execute('''
                    SELECT category, COUNT(*) 
                    FROM simple_news 
                    WHERE year=? AND month=?
                    GROUP BY category
                ''', (year, month)).fetchall())
                
                top_news = conn.execute('''
                    SELECT title, url, source, published_date
                    FROM simple_news 
                    WHERE year=? AND month=?
                    ORDER BY published_date DESC
                    LIMIT 5
                ''', (year, month)).fetchall()
                
                months_data[f"{year}-{month:02d}"] = {
                    'month_name': month_name,
                    'total': count,
                    'categories': categories,
                    'top_news': [list(row) for row in top_news]
                }
        
        # Сохранение отчета
        output_file = f"data/simple_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(months_data, f, ensure_ascii=False, indent=2)
        
        print(f"Отчет сохранен: {output_file}")
        return output_file

def main():
    """Главная функция"""
    collector = SimpleHistoricalCollector()
    
    try:
        # Сбор
        stats = collector.collect_news()
        
        # Отчет
        report_file = collector.generate_report()
        
        print(f"\nСбор завершен успешно!")
        print(f"Отчет: {report_file}")
        
        return 0
        
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1

if __name__ == "__main__":
    exit(main())