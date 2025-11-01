#!/usr/bin/env python3
"""
Улучшенная версия простого RSS скрипта
Без ошибок datetime и с лучшей обработкой
"""

import feedparser
import requests
from datetime import datetime, timezone
import time

RSS_SOURCES = [
    # Kubernetes official
    "https://kubernetes.io/feed.xml",
    "https://github.com/kubernetes/kubernetes/releases.atom",
    "https://github.com/kubernetes/minikube/releases.atom",
    "https://github.com/kubernetes-sigs/kind/releases.atom",
    "https://github.com/k3s-io/k3s/releases.atom",

    # Docker official
    "https://www.docker.com/blog/feed/",
    "https://github.com/docker/docker-ce/releases.atom",
    "https://github.com/docker/cli/releases.atom",
    "https://github.com/moby/moby/releases.atom",
    "https://github.com/docker/compose/releases.atom",

    # Podman, containers
    "https://github.com/containers/podman/releases.atom",
    "https://github.com/containers/buildah/releases.atom",
    "https://github.com/containers/skopeo/releases.atom",
    "https://github.com/cri-o/cri-o/releases.atom",

    # Container infrastructure engines
    "https://github.com/containerd/containerd/releases.atom",
    "https://github.com/opencontainers/runc/releases.atom",
    "https://github.com/opencontainers/image-spec/releases.atom",

    # Community/aggregators
    "https://habr.com/ru/rss/search/?q=docker+podman+контейнеры&target_type=posts",
    "https://dev.to/feed/tag/docker",
    "https://dev.to/feed/tag/container",
    "https://dev.to/feed/tag/kubernetes"
]

def parse_date_safe(date_str):
    """Безопасный парсинг даты"""
    if not date_str:
        return datetime.now(timezone.utc)
    
    try:
        # feedparser обычно парсит даты автоматически
        if hasattr(date_str, 'tm_year'):  # struct_time
            return datetime(*date_str[:6], tzinfo=timezone.utc)
        return datetime.now(timezone.utc)
    except:
        return datetime.now(timezone.utc)

def fetch_rss_news():
    news = []
    success_count = 0
    error_count = 0
    
    print(f"🚀 Начинаю сбор из {len(RSS_SOURCES)} источников...")
    
    for i, url in enumerate(RSS_SOURCES, 1):
        print(f"[{i}/{len(RSS_SOURCES)}] {url}")
        
        try:
            headers = {
                'User-Agent': 'SimpleRSSCollector/1.0'
            }
            response = requests.get(url, timeout=(10, 30), headers=headers)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if feed.bozo:
                print(f"  ⚠️  Некорректный RSS")
            
            entry_count = 0
            for entry in feed.entries[:5]:  # Только 5 записей на источник
                pub_date = parse_date_safe(entry.get("published_parsed"))
                
                news.append({
                    "title": entry.title,
                    "link": entry.link,
                    "date": pub_date.strftime("%Y-%m-%d %H:%M"),
                    "date_obj": pub_date,
                    "summary": entry.get("summary", "")[:200] + "...",
                    "source": url.split('/')[2]  # Домен источника
                })
                entry_count += 1
            
            print(f"  ✅ {entry_count} новостей")
            success_count += 1
            time.sleep(1)  # Пауза между запросами
            
        except requests.exceptions.Timeout:
            print(f"  ⏰ Timeout")
            error_count += 1
        except requests.exceptions.ConnectionError:
            print(f"  🔌 Connection error")  
            error_count += 1
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            error_count += 1
    
    print(f"\n📊 Статистика: ✅{success_count} ❌{error_count}")
    return news

def filter_recent_news(news_list, hours=24):
    """Фильтр только свежих новостей"""
    now = datetime.now(timezone.utc)
    recent = []
    
    for item in news_list:
        if (now - item['date_obj']).total_seconds() < hours * 3600:
            recent.append(item)
    
    return sorted(recent, key=lambda x: x['date_obj'], reverse=True)

if __name__ == "__main__":
    try:
        print("=== 📰 Container Technologies News Collector ===\n")
        
        news_list = fetch_rss_news()
        print(f"\n📰 Всего собрано: {len(news_list)} новостей")
        
        # Фильтр свежих новостей (последние 24 часа)
        recent_news = filter_recent_news(news_list, hours=24)
        print(f"🔥 Свежие (24ч): {len(recent_news)} новостей")
        
        print("\n=== 🔥 СВЕЖИЕ НОВОСТИ ===")
        for item in recent_news[:10]:
            print(f"📅 {item['date']}")
            print(f"📰 {item['title']}")
            print(f"🔗 {item['link']}")
            print(f"🌐 {item['source']}")
            print(f"📝 {item['summary']}")
            print("-" * 80)
            
    except Exception as e:
        print(f"❌ Глобальная ошибка: {e}")