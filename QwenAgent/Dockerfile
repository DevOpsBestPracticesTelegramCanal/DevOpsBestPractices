FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY core/ core/
COPY tests/ tests/
COPY swebench_tasks/ swebench_tasks/
COPY benchmark/ benchmark/
COPY templates/ templates/
COPY qwencode_server.py .
COPY Makefile .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5002/health')" || exit 1

EXPOSE 5002

CMD ["python", "qwencode_server.py"]
