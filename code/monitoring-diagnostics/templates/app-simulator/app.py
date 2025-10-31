#!/usr/bin/env python3
"""
Симулятор приложения для генерации метрик Four Golden Signals
GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
Telegram: @DevOps_best_practices
"""

import time
import random
import threading
from flask import Flask, request, jsonify
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Prometheus метрики
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'code']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Симуляция нагрузки
def generate_traffic():
    """Генерирует фоновый трафик для реалистичных метрик"""
    endpoints = ['/api/users', '/api/orders', '/api/products', '/health', '/']
    methods = ['GET', 'POST', 'PUT', 'DELETE']
    
    while True:
        endpoint = random.choice(endpoints)
        method = random.choice(methods)
        
        # Симуляция времени ответа
        if endpoint == '/health':
            duration = random.uniform(0.001, 0.01)  # Быстрый endpoint
            status_code = 200
        elif endpoint == '/api/orders':
            duration = random.uniform(0.1, 0.5)  # Медленный endpoint
            # Иногда генерируем ошибки
            status_code = random.choices([200, 500], weights=[95, 5])[0]
        else:
            duration = random.uniform(0.01, 0.2)  # Обычные endpoints
            status_code = random.choices([200, 400, 500], weights=[90, 8, 2])[0]
        
        # Записываем метрики
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, code=status_code).inc()
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
        
        # Пауза между запросами
        time.sleep(random.uniform(0.1, 1.0))

@app.route('/')
def index():
    """Главная страница"""
    REQUEST_COUNT.labels(method='GET', endpoint='/', code=200).inc()
    with REQUEST_DURATION.labels(method='GET', endpoint='/').time():
        time.sleep(random.uniform(0.01, 0.05))
    return jsonify({
        'service': 'monitoring-demo-app',
        'status': 'running',
        'endpoints': ['/health', '/api/users', '/api/orders', '/api/products', '/metrics']
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    REQUEST_COUNT.labels(method='GET', endpoint='/health', code=200).inc()
    with REQUEST_DURATION.labels(method='GET', endpoint='/health').time():
        time.sleep(random.uniform(0.001, 0.01))
    return jsonify({'status': 'healthy'})

@app.route('/api/users')
def users():
    """Users API endpoint"""
    # Симуляция случайных ошибок
    if random.random() < 0.05:  # 5% ошибок
        REQUEST_COUNT.labels(method='GET', endpoint='/api/users', code=500).inc()
        return jsonify({'error': 'Internal server error'}), 500
    
    REQUEST_COUNT.labels(method='GET', endpoint='/api/users', code=200).inc()
    with REQUEST_DURATION.labels(method='GET', endpoint='/api/users').time():
        time.sleep(random.uniform(0.05, 0.15))
    
    return jsonify({
        'users': [
            {'id': i, 'name': f'User {i}'} 
            for i in range(1, random.randint(5, 20))
        ]
    })

@app.route('/api/orders')
def orders():
    """Orders API endpoint (медленный)"""
    # Симуляция высокой задержки и ошибок
    if random.random() < 0.1:  # 10% ошибок
        REQUEST_COUNT.labels(method='GET', endpoint='/api/orders', code=500).inc()
        return jsonify({'error': 'Database connection failed'}), 500
    
    REQUEST_COUNT.labels(method='GET', endpoint='/api/orders', code=200).inc()
    with REQUEST_DURATION.labels(method='GET', endpoint='/api/orders').time():
        # Симуляция медленного запроса к базе данных
        time.sleep(random.uniform(0.2, 0.8))
    
    return jsonify({
        'orders': [
            {'id': i, 'amount': random.randint(10, 1000)} 
            for i in range(1, random.randint(1, 10))
        ]
    })

@app.route('/api/products')
def products():
    """Products API endpoint"""
    # Симуляция client errors
    if random.random() < 0.08:  # 8% client errors
        REQUEST_COUNT.labels(method='GET', endpoint='/api/products', code=400).inc()
        return jsonify({'error': 'Bad request'}), 400
    
    REQUEST_COUNT.labels(method='GET', endpoint='/api/products', code=200).inc()
    with REQUEST_DURATION.labels(method='GET', endpoint='/api/products').time():
        time.sleep(random.uniform(0.03, 0.12))
    
    return jsonify({
        'products': [
            {'id': i, 'name': f'Product {i}', 'price': random.randint(10, 500)} 
            for i in range(1, random.randint(3, 15))
        ]
    })

@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

@app.errorhandler(404)
def not_found(error):
    REQUEST_COUNT.labels(method=request.method, endpoint=request.path, code=404).inc()
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(error):
    REQUEST_COUNT.labels(method=request.method, endpoint=request.path, code=500).inc()
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Запускаем генератор фонового трафика
    traffic_thread = threading.Thread(target=generate_traffic, daemon=True)
    traffic_thread.start()
    
    logger.info("Starting monitoring demo application...")
    logger.info("Metrics available at: http://localhost:8080/metrics")
    logger.info("Health check at: http://localhost:8080/health")
    
    # Запускаем Flask приложение
    app.run(host='0.0.0.0', port=8080, debug=False)