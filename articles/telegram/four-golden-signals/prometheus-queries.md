# Prometheus запросы для Four Golden Signals

## 1. 📊 Latency (Задержка)

### Медианное время ответа (p50)
```promql
histogram_quantile(0.5, http_request_duration_seconds_bucket{job="demo-app"})
```

### 95-й процентиль задержки
```promql
histogram_quantile(0.95, http_request_duration_seconds_bucket{job="demo-app"})
```

### 99-й процентиль задержки
```promql
histogram_quantile(0.99, http_request_duration_seconds_bucket{job="demo-app"})
```

## 2. 🚀 Traffic (Трафик)

### Requests per second (RPS)
```promql
rate(http_requests_total{job="demo-app"}[5m])
```

### Общий трафик по эндпоинтам
```promql
sum by (endpoint) (rate(http_requests_total{job="demo-app"}[5m]))
```

### Топ-5 самых нагруженных эндпоинтов
```promql
topk(5, sum by (endpoint) (rate(http_requests_total{job="demo-app"}[5m])))
```

## 3. ❌ Errors (Ошибки)

### Процент ошибок (Error Rate)
```promql
rate(http_requests_total{job="demo-app",code=~"[45].."}[5m]) / 
rate(http_requests_total{job="demo-app"}[5m]) * 100
```

### Количество 5xx ошибок в минуту
```promql
increase(http_requests_total{job="demo-app",code=~"5.."}[1m])
```

### Количество 4xx ошибок в минуту
```promql
increase(http_requests_total{job="demo-app",code=~"4.."}[1m])
```

## 4. 🔄 Saturation (Насыщение)

### CPU загрузка
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

### Использование памяти
```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Загрузка диска
```promql
100 - (node_filesystem_avail_bytes / node_filesystem_size_bytes * 100)
```

### Сетевая нагрузка (входящий трафик)
```promql
rate(node_network_receive_bytes_total[5m]) * 8 / 1024 / 1024
```

## 🎯 Готовые алерты

### Высокая задержка
```promql
histogram_quantile(0.95, http_request_duration_seconds_bucket{job="demo-app"}) > 0.5
```

### Высокий процент ошибок
```promql
rate(http_requests_total{job="demo-app",code=~"[45].."}[5m]) / 
rate(http_requests_total{job="demo-app"}[5m]) > 0.05
```

### Высокая загрузка CPU
```promql
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
```

### Мало свободной памяти
```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
```