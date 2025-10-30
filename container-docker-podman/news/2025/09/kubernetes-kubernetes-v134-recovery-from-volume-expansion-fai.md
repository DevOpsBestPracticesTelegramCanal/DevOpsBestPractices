# Kubernetes v1.34: Recovery From Volume Expansion Failure (GA)

## 📋 Метаинформация

- **Дата публикации**: 2025-09-19
- **Категория**: kubernetes
- **Важность**: 5/5 ⭐⭐⭐⭐⭐
- **Тип**: release
- **Статус**: stable
- **Источник**: kubernetes.io

## 🎯 Краткое описание

<p>Have you ever made a typo when expanding your persistent volumes in Kubernetes? Meant to specify <code>2TB</code>
but specified <code>20TiB</code>? This seemingly innocuous problem was kinda hard t...

## 📝 Детальная информация

### Основные изменения
<p>Have you ever made a typo when expanding your persistent volumes in Kubernetes? Meant to specify <code>2TB</code>
but specified <code>20TiB</code>? This seemingly innocuous problem was kinda hard to fix - and took the project almost 5 years to fix.
<a href="https://kubernetes.io/docs/concepts/storage/persistent-volumes/#recovering-from-failure-when-expanding-volumes">Automated recovery from storage expansion</a> has been around for a while in beta; however, with the v1.34 release, we have gra

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

- **Источник**: [Kubernetes v1.34: Recovery From Volume Expansion Failure (GA)][main-link]

[main-link]: https://kubernetes.io/blog/2025/09/19/kubernetes-v1-34-recover-expansion-failure/

## 📱 Аннотация для Telegram

```
⚙️ **Kubernetes v1.34: Recovery From Volume Expansion Failure (GA)**

<p>Have you ever made a typo when expanding your persistent volumes in Kubernetes? Meant to specify <code>2TB</code>
but specified <code>20TiB</code>?...

🔗 [Подробнее][tg-link]
📅 2025-09-19
⭐ Важность: 5/5

#kubernetes #containers #devops

[tg-link]: https://kubernetes.io/blog/2025/09/19/kubernetes-v1-34-recover-expansion-failure/
```

## 🏷️ Теги

- kubernetes
- release
- stable
- containers
- devops

---
*Собрано автоматической системой новостей Container Technologies*