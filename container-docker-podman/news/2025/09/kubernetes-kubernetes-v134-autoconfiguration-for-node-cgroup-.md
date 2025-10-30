# Kubernetes v1.34: Autoconfiguration for Node Cgroup Driver Goes GA

## 📋 Метаинформация

- **Дата публикации**: 2025-09-12
- **Категория**: kubernetes
- **Важность**: 5/5 ⭐⭐⭐⭐⭐
- **Тип**: release
- **Статус**: stable
- **Источник**: kubernetes.io

## 🎯 Краткое описание

<p>Historically, configuring the correct cgroup driver has been a pain point for users running new
Kubernetes clusters. On Linux systems, there are two different cgroup drivers:
<code>cgroupfs</code> ...

## 📝 Детальная информация

### Основные изменения
<p>Historically, configuring the correct cgroup driver has been a pain point for users running new
Kubernetes clusters. On Linux systems, there are two different cgroup drivers:
<code>cgroupfs</code> and <code>systemd</code>. In the past, both the <a href="https://kubernetes.io/docs/reference/command-line-tools-reference/kubelet/">kubelet</a>
and CRI implementation (like CRI-O or containerd) needed to be configured to use
the same cgroup driver, or else the kubelet would misbehave without any ex

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

- **Источник**: [Kubernetes v1.34: Autoconfiguration for Node Cgroup Driver Goes GA][main-link]

[main-link]: https://kubernetes.io/blog/2025/09/12/kubernetes-v1-34-cri-cgroup-driver-lookup-now-ga/

## 📱 Аннотация для Telegram

```
⚙️ **Kubernetes v1.34: Autoconfiguration for Node Cgroup Driver Goes GA**

<p>Historically, configuring the correct cgroup driver has been a pain point for users running new
Kubernetes clusters. On Linux systems, there are tw...

🔗 [Подробнее][tg-link]
📅 2025-09-12
⭐ Важность: 5/5

#kubernetes #containers #devops

[tg-link]: https://kubernetes.io/blog/2025/09/12/kubernetes-v1-34-cri-cgroup-driver-lookup-now-ga/
```

## 🏷️ Теги

- kubernetes
- release
- stable
- containers
- devops

---
*Собрано автоматической системой новостей Container Technologies*