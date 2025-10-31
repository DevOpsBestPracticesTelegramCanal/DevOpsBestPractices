#!/usr/bin/env python3
"""
Генератор нагрузки для демо-приложения
Создает реалистичный трафик для тестирования Four Golden Signals
GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
Telegram: @DevOps_best_practices
"""

import asyncio
import aiohttp
import random
import time
import logging
from typing import List, Dict

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LoadGenerator:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session = None
        self.endpoints = [
            {'path': '/', 'weight': 30},
            {'path': '/health', 'weight': 20},
            {'path': '/api/users', 'weight': 25},
            {'path': '/api/orders', 'weight': 15},
            {'path': '/api/products', 'weight': 10}
        ]
        
    async def create_session(self):
        """Создание HTTP сессии"""
        timeout = aiohttp.ClientTimeout(total=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        
    async def close_session(self):
        """Закрытие HTTP сессии"""
        if self.session:
            await self.session.close()
            
    async def make_request(self, endpoint: str) -> Dict:
        """Выполнение HTTP запроса"""
        try:
            start_time = time.time()
            
            async with self.session.get(f"{self.base_url}{endpoint}") as response:
                duration = time.time() - start_time
                content = await response.text()
                
                return {
                    'endpoint': endpoint,
                    'status_code': response.status,
                    'duration': duration,
                    'success': 200 <= response.status < 400
                }
                
        except asyncio.TimeoutError:
            return {
                'endpoint': endpoint,
                'status_code': 408,
                'duration': 10.0,
                'success': False,
                'error': 'timeout'
            }
        except Exception as e:
            return {
                'endpoint': endpoint,
                'status_code': 500,
                'duration': 0,
                'success': False,
                'error': str(e)
            }
    
    def get_weighted_endpoint(self) -> str:
        """Выбор endpoint с учетом весов"""
        endpoints = [ep['path'] for ep in self.endpoints]
        weights = [ep['weight'] for ep in self.endpoints]
        return random.choices(endpoints, weights=weights)[0]
    
    async def generate_steady_load(self, rps: int = 10, duration: int = 300):
        """Генерация стабильной нагрузки"""
        logger.info(f"Generating steady load: {rps} RPS for {duration} seconds")
        
        end_time = time.time() + duration
        interval = 1.0 / rps
        
        while time.time() < end_time:
            endpoint = self.get_weighted_endpoint()
            result = await self.make_request(endpoint)
            
            if not result['success']:
                logger.warning(f"Request failed: {result}")
            
            await asyncio.sleep(interval)
    
    async def generate_spike_load(self, base_rps: int = 10, spike_rps: int = 100, 
                                 spike_duration: int = 30):
        """Генерация нагрузки с пиками"""
        logger.info(f"Generating spike load: {base_rps} -> {spike_rps} RPS")
        
        # Базовая нагрузка
        await self.generate_steady_load(base_rps, 60)
        
        # Пик нагрузки
        logger.info(f"Starting spike: {spike_rps} RPS for {spike_duration}s")
        await self.generate_steady_load(spike_rps, spike_duration)
        
        # Возврат к базовой нагрузке
        logger.info(f"Returning to base load: {base_rps} RPS")
        await self.generate_steady_load(base_rps, 60)
    
    async def generate_error_burst(self, duration: int = 60):
        """Генерация всплеска ошибок"""
        logger.info(f"Generating error burst for {duration} seconds")
        
        end_time = time.time() + duration
        
        while time.time() < end_time:
            # Увеличиваем вероятность запросов к проблемным endpoints
            if random.random() < 0.7:
                endpoint = '/api/orders'  # Медленный endpoint с ошибками
            else:
                endpoint = self.get_weighted_endpoint()
                
            result = await self.make_request(endpoint)
            await asyncio.sleep(0.1)  # 10 RPS
    
    async def run_realistic_scenario(self):
        """Реалистичный сценарий нагрузки"""
        scenarios = [
            ("Normal traffic", self.generate_steady_load, {'rps': 5, 'duration': 120}),
            ("Peak hours", self.generate_steady_load, {'rps': 15, 'duration': 180}),
            ("Traffic spike", self.generate_spike_load, {'base_rps': 10, 'spike_rps': 50, 'spike_duration': 45}),
            ("Error burst", self.generate_error_burst, {'duration': 90}),
            ("Recovery", self.generate_steady_load, {'rps': 8, 'duration': 120})
        ]
        
        for name, func, kwargs in scenarios:
            logger.info(f"Starting scenario: {name}")
            await func(**kwargs)
            logger.info(f"Completed scenario: {name}")
            
            # Пауза между сценариями
            await asyncio.sleep(30)

async def main():
    """Главная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Load generator for demo app')
    parser.add_argument('--url', default='http://localhost:8080', 
                       help='Base URL of the demo app')
    parser.add_argument('--mode', choices=['steady', 'spike', 'errors', 'realistic'], 
                       default='realistic', help='Load generation mode')
    parser.add_argument('--rps', type=int, default=10, 
                       help='Requests per second for steady mode')
    parser.add_argument('--duration', type=int, default=300, 
                       help='Duration in seconds')
    
    args = parser.parse_args()
    
    generator = LoadGenerator(args.url)
    
    try:
        await generator.create_session()
        
        # Проверка доступности приложения
        result = await generator.make_request('/health')
        if not result['success']:
            logger.error(f"Demo app not available at {args.url}")
            return
            
        logger.info(f"Demo app is available, starting load generation...")
        
        if args.mode == 'steady':
            await generator.generate_steady_load(args.rps, args.duration)
        elif args.mode == 'spike':
            await generator.generate_spike_load(args.rps, args.rps * 5, 60)
        elif args.mode == 'errors':
            await generator.generate_error_burst(args.duration)
        elif args.mode == 'realistic':
            await generator.run_realistic_scenario()
            
    except KeyboardInterrupt:
        logger.info("Load generation stopped by user")
    except Exception as e:
        logger.error(f"Error during load generation: {e}")
    finally:
        await generator.close_session()

if __name__ == "__main__":
    asyncio.run(main())