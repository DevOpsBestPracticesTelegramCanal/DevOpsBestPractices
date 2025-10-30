# Docker Compose v2.40.3

## 📋 Метаинформация

- **Дата публикации**: 2025-10-30
- **Категория**: docker
- **Важность**: 4/5 ⭐⭐⭐⭐
- **Тип**: release
- **Статус**: stable
- **Источник**: https://github.com/docker/compose/releases
- **Автор**: Docker Team

## 🎯 Краткое описание

Новая версия Docker Compose v2.40.3 с важными исправлениями для OCI compose override поддержки и улучшениями команды exec.

## 📝 Детальная информация

### 🐛 Исправления (Fixes)

#### 1. OCI Compose Override Support
- **Проблема**: Некорректная работа с OCI compose override
- **Решение**: Полное исправление поддержки OCI стандарта
- **PR**: [#13311](https://github.com/docker/compose/pull/13311)
- **Автор**: @ndeloof

#### 2. Help Output для exec --no-tty
- **Проблема**: Неправильный вывод help для опции --no-tty
- **Решение**: Исправлен текст справки
- **Автор**: @tonyo

### Совместимость
- ✅ **Обратная совместимость** с предыдущими версиями v2.40.x
- ✅ **OCI стандарт** полностью поддержан
- ✅ **Docker Engine** всех поддерживаемых версий

### Для кого
- **Docker Compose пользователи**
- **DevOps инженеры**
- **Разработчики** использующие containerized development
- **CI/CD системы** с Docker Compose

### Рекомендации
- ✅ **Рекомендуется обновление** для всех пользователей
- ✅ Особенно важно для пользователей **OCI override**
- ✅ Безопасное обновление (только bugfixes)
- ⚠️ Тестирование в dev/staging перед production

## 🔗 Ссылки

- **Release**: https://github.com/docker/compose/releases/tag/v2.40.3
- **Changelog**: Доступен на странице релиза
- **Pull Requests**: 
  - [OCI fix #13311](https://github.com/docker/compose/pull/13311)
- **Docker Compose Docs**: https://docs.docker.com/compose/

## 📱 Аннотация для Telegram

```
🐳 **Docker Compose v2.40.3**

🔧 Новая версия Docker Compose с важными исправлениями:

✅ Исправлена поддержка OCI compose override
✅ Исправлен вывод help для опции "exec --no-tty"

Рекомендуется обновление для всех пользователей, особенно использующих OCI стандарт.

🔗 [Скачать обновление][compose-update]

[compose-update]: https://github.com/docker/compose/releases/tag/v2.40.3
📅 30 октября 2025
⭐ Важность: 4/5

#docker #compose #update #bugfix #oci #containers #devops
```

## 🏷️ Теги

- docker
- compose
- release
- bugfix
- oci
- override
- exec
- update
- stable
- containers
- devops

---
*Собрано автоматической системой новостей Container Technologies*