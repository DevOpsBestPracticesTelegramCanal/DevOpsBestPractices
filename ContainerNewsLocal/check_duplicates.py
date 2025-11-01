#!/usr/bin/env python3
import sqlite3
from collections import Counter

def check_duplicates():
    """Проверка дубликатов в базе данных"""
    
    conn = sqlite3.connect('data/comprehensive_news.db')
    
    # Проверка дубликатов по URL
    print("=== Проверка дубликатов по URL ===")
    url_counts = conn.execute('''
        SELECT url, COUNT(*) as count
        FROM comprehensive_news 
        GROUP BY url 
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    ''').fetchall()
    
    if url_counts:
        print(f"Найдено {len(url_counts)} дублированных URL:")
        for url, count in url_counts[:10]:
            print(f"  {count}x: {url}")
    else:
        print("OK Дубликатов по URL не найдено")
    
    # Проверка дубликатов по заголовкам
    print("\n=== Проверка дубликатов по заголовкам ===")
    title_counts = conn.execute('''
        SELECT title, COUNT(*) as count
        FROM comprehensive_news 
        GROUP BY title 
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    ''').fetchall()
    
    if title_counts:
        print(f"Найдено {len(title_counts)} дублированных заголовков:")
        for title, count in title_counts[:10]:
            print(f"  {count}x: {title[:80]}...")
    else:
        print("OK Дубликатов по заголовкам не найдено")
    
    # Проверка дубликатов по hash_id
    print("\n=== Проверка дубликатов по hash_id ===")
    hash_counts = conn.execute('''
        SELECT hash_id, COUNT(*) as count
        FROM comprehensive_news 
        GROUP BY hash_id 
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    ''').fetchall()
    
    if hash_counts:
        print(f"Найдено {len(hash_counts)} дублированных hash_id:")
        for hash_id, count in hash_counts[:5]:
            print(f"  {count}x: {hash_id}")
    else:
        print("OK Дубликатов по hash_id не найдено")
    
    # Общая статистика
    total = conn.execute("SELECT COUNT(*) FROM comprehensive_news").fetchone()[0]
    unique_urls = conn.execute("SELECT COUNT(DISTINCT url) FROM comprehensive_news").fetchone()[0]
    unique_titles = conn.execute("SELECT COUNT(DISTINCT title) FROM comprehensive_news").fetchone()[0]
    
    print(f"\n=== Общая статистика ===")
    print(f"Всего записей: {total}")
    print(f"Уникальных URL: {unique_urls}")
    print(f"Уникальных заголовков: {unique_titles}")
    
    conn.close()

if __name__ == "__main__":
    check_duplicates()