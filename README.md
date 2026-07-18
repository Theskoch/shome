# Home Services Dashboard

Удобная self-hosted панель сервисов с авторизацией через LDAP/AD, загрузкой иконок, фоном и редактированием карточек прямо из UI.

## Что умеет

- 🔐 Логин через LDAP/Active Directory
- 🧩 Добавление/редактирование/удаление сервисов в интерфейсе
- 🖼 Загрузка иконок (PNG/JPG/WEBP/SVG и др.)
- 🌄 Смена фонового изображения
- 🧹 Автоочистка неиспользуемых файлов в `uploads/`
- 💾 Хранение настроек в `App_Data/*.json`

---

## Структура проекта

```text
app.py                  # Flask backend + API
iisstart.htm            # основная страница дашборда
login.htm               # страница логина
css.css                 # стили
assets/                 # SVG и статические ресурсы
uploads/                # загруженные иконки/фоны (создаётся/используется автоматически)
App_Data/
  ├─ services.json      # список карточек
  ├─ settings.json      # настройки UI (например фон)
  └─ ldap_config.json   # LDAP-конфиг
```

---

## Быстрый старт

### Вариант 1: Docker Compose (рекомендуется)

Конфиг и данные лежат на хосте рядом с compose, в образе только код —
пересборка их не трогает. Подробности в **[docker/README.md](docker/README.md)**.

```bash
cd docker
cp .env.example .env            # порт, ключ сессий, UID/GID
nano config/ldap_config.json    # server_uri, bind_password, search_base
docker compose up -d
```

### Вариант 2: локально

#### 1) Требования

- Python **3.10+**
- Доступ к LDAP/AD серверу

#### 2) Установка зависимостей

В проекте есть папка `_pydeps` со времён IIS, но `ldap3` в ней нет — ставьте зависимости сами:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r docker/requirements.txt
```

#### 3) Настройка LDAP

Заполните файл `App_Data/ldap_config.json` (в Docker — `docker/config/ldap_config.json`).

Минимальный рабочий пример:

```json
{
  "server_uri": "ldap://home.local",
  "use_ssl": false,
  "bind_dn": "CN=ldap-reader,DC=home,DC=local",
  "bind_password": "CHANGE_ME",
  "search_base": "DC=home,DC=local",
  "search_filter": "(sAMAccountName={username})",
  "required_group_dn": "CN=HomeServicesUsers,OU=Groups,DC=home,DC=local",
  "session_days": 30,
  "secret_key": "CHANGE_ME_TO_RANDOM_STRING"
}
```

> ⚠️ Обязательно замените `bind_password` и `secret_key`.

#### 4) Запуск

```bash
python3 app.py
```

По умолчанию приложение поднимется на:

- `http://localhost:8080`

Порт меняется переменной `SHOME_PORT`, отладка включается `SHOME_DEBUG=1`.
Полный список переменных — в [CLAUDE.md](CLAUDE.md).

---

## Что и где заполнять (ключи настроек)

Файл: `App_Data/ldap_config.json`

| Ключ | Обязательный | Пример | Описание |
|---|---|---|---|
| `server_uri` | ✅ | `ldap://home.local` | URI LDAP/AD сервера |
| `use_ssl` | ⛔ (рекоменд.) | `false` / `true` | Подключение по SSL |
| `bind_dn` | ✅* | `CN=ldap-reader,DC=home,DC=local` | Сервисная учётка для поиска пользователя |
| `bind_password` | ✅* | `secret` | Пароль сервисной учётки |
| `search_base` | ✅* | `DC=home,DC=local` | База поиска пользователей |
| `search_filter` | ⛔ | `(sAMAccountName={username})` | LDAP-фильтр поиска. `{username}` обязателен |
| `required_group_dn` | ⛔ | `CN=HomeServicesUsers,...` | Ограничение входа по группе |
| `session_days` | ⛔ | `30` | Срок жизни сессии в днях |
| `secret_key` | ✅ | `long-random-string` | Ключ подписи Flask-сессий |
| `user_dn_template` | альтернативно | `uid={username},ou=users,dc=home,dc=local` | Вариант входа БЕЗ `bind_dn`-поиска |

\* Обязательны, если **не** используется `user_dn_template`.

### Два режима LDAP-авторизации

1. **Через поиск пользователя (рекомендуется для AD)**
   - Используются: `bind_dn`, `bind_password`, `search_base`, `search_filter`

2. **Через шаблон DN**
   - Используется: `user_dn_template`
   - Тогда сервисный bind не нужен

---

## Где хранятся данные

- `App_Data/services.json` — карточки сервисов
- `App_Data/settings.json` — фон и другие UI-настройки
- `uploads/` — загруженные картинки

---

## Частые проблемы

### Не могу войти (401)
- Проверьте `server_uri`, `bind_dn`, `bind_password`
- Проверьте `search_filter` (должен содержать `{username}`)
- Проверьте, что пользователь входит в `required_group_dn` (если используется)

### Иконки не отображаются
- Проверьте, что файл реально лежит в `uploads/`
- Обновите страницу с hard refresh (`Ctrl/Cmd + Shift + R`)

### Сессии «слетают»
- Убедитесь, что `secret_key` задан и не меняется при каждом запуске

---

## API (кратко)

- `POST /api/auth/login` — вход
- `POST /api/auth/logout` — выход
- `GET /api/auth/status` — статус сессии
- `GET/POST /api/services` — список/сохранение сервисов
- `GET/POST /api/settings` — настройки
- `POST /api/upload` — загрузка файла

---

## Безопасность (важно)

- Не коммитьте реальные пароли в `ldap_config.json` — он в `.gitignore`
- Используйте длинный случайный `secret_key`: `openssl rand -hex 32`
- Для production лучше запускать за reverse proxy (Nginx/Caddy) + HTTPS.
  За прокси включайте `SHOME_TRUST_PROXY=1`, иначе защита от перебора
  посчитает всех клиентов одним IP
- Debug выключен по умолчанию, включается только через `SHOME_DEBUG=1`

### Что закрыто

- **Статика.** Раздаётся только `assets/`. Раньше `static_folder` смотрел в корень проекта,
  и `/App_Data/ldap_config.json` (с паролем bind-учётки), `/app.py` и `/.git/` отдавались
  без авторизации. Если где-то остался старый деплой — там эта дыра ещё живая.
- **Перебор паролей.** 10 попыток с одного IP, затем пауза 5 минут, затем новые 10
  (`SHOME_LOGIN_MAX_ATTEMPTS`, `SHOME_LOGIN_BLOCK_MINUTES`). Иначе перебор идёт прямо в AD
  и лочит доменные учётки.
- **Загрузки.** Принимаются только картинки по белому списку расширений; `/uploads/*` требует
  сессию и отдаётся с `nosniff` + CSP (иначе SVG со скриптом выполнялся бы на своём origin).
