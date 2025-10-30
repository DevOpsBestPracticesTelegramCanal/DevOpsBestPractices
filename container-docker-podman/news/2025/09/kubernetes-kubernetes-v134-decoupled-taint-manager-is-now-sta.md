# Kubernetes v1.34: Decoupled Taint Manager Is Now Stable

## 📋 Метаинформация

- **Дата публикации**: 2025-09-15
- **Категория**: kubernetes
- **Важность**: 5/5 ⭐⭐⭐⭐⭐
- **Тип**: release
- **Статус**: stable
- **Источник**: kubernetes.io

## 🎯 Краткое описание

<p>This enhancement separates the responsibility of managing node lifecycle and pod eviction into two distinct components.
Previously, the node lifecycle controller handled both marking nodes as unhea...

## 📝 Детальная информация

### Основные изменения
<p>This enhancement separates the responsibility of managing node lifecycle and pod eviction into two distinct components.
Previously, the node lifecycle controller handled both marking nodes as unhealthy with NoExecute taints and evicting pods from them.
Now, a dedicated taint eviction controller manages the eviction process, while the node lifecycle controller focuses solely on applying taints.
This separation not only improves code organization but also makes it easier to improve taint evicti

### Для кого
- **Разработчики** kubernetes
- **DevOps инженеры**
- **Platform engineers**
- **Системные администраторы**

### Рекомендации
- ✅ Подходит для тестирования
- ⚠️ Проверьте совместимость
- 📋 Изучите changelog перед обновлением

## 🔗 Ссылки

- **Источник**: [Kubernetes v1.34: Decoupled Taint Manager Is Now Stable][main-link]

[main-link]: https://kubernetes.io/blog/2025/09/15/kubernetes-v1-34-decoupled-taint-manager-is-now-stable/

## 📱 Аннотация для Telegram

```
⚙️ **Kubernetes v1.34: Decoupled Taint Manager Is Now Stable**

<p>This enhancement separates the responsibility of managing node lifecycle and pod eviction into two distinct components.
Previously, the node lifecy...

🔗 [Подробнее][tg-link]
📅 2025-09-15
⭐ Важность: 5/5

#kubernetes #containers #devops

[tg-link]: https://kubernetes.io/blog/2025/09/15/kubernetes-v1-34-decoupled-taint-manager-is-now-stable/
```

## 🏷️ Теги

- kubernetes
- release
- stable
- containers
- devops

---
*Собрано автоматической системой новостей Container Technologies*