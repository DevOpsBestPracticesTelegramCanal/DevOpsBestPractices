#!/usr/bin/env python3
"""
Debug script to see what dates are available in RSS feeds
"""

import feedparser
import requests
from datetime import datetime

sources = [
    'https://kubernetes.io/feed.xml',
    'https://www.docker.com/blog/feed/',
    'https://dev.to/feed/tag/docker',
    'https://dev.to/feed/tag/kubernetes'
]

def parse_date(date_str):
    if not date_str:
        return None
    try:
        parsed = feedparser._parse_date(date_str)
        if parsed:
            return datetime(*parsed[:6])
    except:
        pass
    return None

print("Проверка дат в RSS источниках:\n")

for source in sources:
    print(f"Источник: {source}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(source, timeout=30, headers=headers)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        
        print(f"  Записей в feed: {len(feed.entries)}")
        
        dates = []
        for i, entry in enumerate(feed.entries[:5]):
            pub_date_str = entry.get('published', '')
            pub_date = parse_date(pub_date_str)
            print(f"    [{i+1}] {entry.get('title', 'No title')[:50]}...")
            print(f"        Дата строка: '{pub_date_str}'")
            print(f"        Дата parsed: {pub_date}")
            if pub_date:
                dates.append(pub_date)
        
        if dates:
            dates.sort(reverse=True)
            print(f"  Диапазон: {dates[-1].strftime('%Y-%m-%d')} - {dates[0].strftime('%Y-%m-%d')}")
        else:
            print("  Не удалось распарсить даты")
            
    except Exception as e:
        print(f"  Ошибка: {e}")
    
    print()