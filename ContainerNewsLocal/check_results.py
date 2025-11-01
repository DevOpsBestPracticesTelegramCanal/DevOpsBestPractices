#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def check_comprehensive_results():
    """Проверка результатов сбора comprehensive collector"""
    try:
        conn = sqlite3.connect('data/comprehensive_news.db')
        
        # Общая статистика
        total_count = conn.execute("SELECT COUNT(*) FROM comprehensive_news").fetchone()[0]
        print(f"Всего новостей: {total_count}")
        
        # По категориям
        print("\nПо категориям:")
        categories = conn.execute('''
            SELECT category, COUNT(*) 
            FROM comprehensive_news 
            GROUP BY category 
            ORDER BY COUNT(*) DESC
        ''').fetchall()
        
        for category, count in categories:
            print(f"  {category}: {count}")
        
        # По источникам
        print("\nТоп источники:")
        sources = conn.execute('''
            SELECT source, COUNT(*) 
            FROM comprehensive_news 
            GROUP BY source 
            ORDER BY COUNT(*) DESC
            LIMIT 10
        ''').fetchall()
        
        for source, count in sources:
            print(f"  {source}: {count}")
        
        # По месяцам
        print("\nПо месяцам:")
        monthly = conn.execute('''
            SELECT strftime('%Y-%m', date_obj) as month, COUNT(*) 
            FROM comprehensive_news 
            WHERE date_obj IS NOT NULL
            GROUP BY month 
            ORDER BY month DESC
        ''').fetchall()
        
        for month, count in monthly:
            print(f"  {month}: {count}")
        
        # Последние новости
        print("\nПоследние 5 новостей:")
        recent = conn.execute('''
            SELECT title, source, published_date
            FROM comprehensive_news 
            ORDER BY date_obj DESC
            LIMIT 5
        ''').fetchall()
        
        for title, source, date in recent:
            print(f"  {date} - {source}")
            print(f"    {title[:80]}...")
        
        conn.close()
        
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    check_comprehensive_results()