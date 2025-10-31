FROM python:3.11-slim

# GitHub: https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices
# Telegram: @DevOps_best_practices

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY app.py .

# Создание пользователя для безопасности
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Порт приложения
EXPOSE 8080

# Проверка здоровья
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Запуск приложения
CMD ["python", "app.py"]