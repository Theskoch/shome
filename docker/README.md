# Разворачивание через Docker Compose

Принцип: **в образе только код, всё настраиваемое — на хосте рядом с compose**.
Пересборка и обновление образа никогда не трогают твой конфиг и данные.

```text
docker/
├─ docker-compose.yml            # порты, монтирования, переменные
├─ Dockerfile                    # сборка образа (правится редко)
├─ requirements.txt              # версии зависимостей
├─ .env                          # ← порт, ключ сессий, UID/GID   (не в git)
├─ config/
│  ├─ ldap_config.json           # ← ЛДАП: сюда лезешь чаще всего  (не в git)
│  └─ ldap_config.json.example   # шаблон с комментариями
└─ data/                         # состояние, монтируется как /data (не в git)
   ├─ App_Data/
   │  ├─ services.json           # карточки сервисов
   │  └─ settings.json           # фон и настройки UI (создастся сам)
   └─ uploads/                   # загруженные иконки и фоны
```

Внутри контейнера: `./config` → `/config` (только чтение), `./data` → `/data` (запись).

## Первый запуск

```bash
cd docker
cp .env.example .env            # проверь HOST_PORT и PUID/PGID
nano config/ldap_config.json    # bind_password, server_uri, search_base
docker compose up -d --build
docker compose logs -f
```

Портал будет на `http://<ip-хоста>:8080` (или на том порту, что в `HOST_PORT`).

Обязательно поменяй перед боем:

- `bind_password` в `config/ldap_config.json` — сейчас там `CHANGE_ME`;
- `secret_key` там же **или** `SHOME_SECRET_KEY` в `.env` — сейчас `CHANGE_ME_TO_RANDOM_STRING`.
  Сгенерировать: `openssl rand -hex 32`. Ключ должен пережить рестарты, иначе всех разлогинит.

`PUID`/`PGID` в `.env` — это владелец каталога `data/`. Подсмотреть свои: `id -u && id -g`.
Не совпадут — контейнер не сможет сохранять карточки и загрузки.

## За Nginx Proxy Manager (боевой вариант)

### 1) Поставить контейнер в сеть NPM

Смотрим, как называется сеть прокси:

```bash
docker network ls | grep -i proxy       # обычно nginx-proxy-manager_default или npm_default
```

В [.env](.env) прописываем её в `NPM_NETWORK`, затем в [docker-compose.yml](docker-compose.yml)
раскомментируем блок `networks:` у сервиса и блок `networks:` внизу файла.

### 2) Убрать публикацию порта

Там же комментируем блок `ports:`. После этого портал доступен **только** через NPM: снаружи
уже не зайти по `http://<ip-сервера>:8082` в обход прокси, сертификата и HSTS.

Нужен прямой доступ для отладки — не убирай совсем, а сузь до localhost: `"127.0.0.1:8082:8080"`.

### 3) Включить флаги прокси в `.env`

```ini
SHOME_TRUST_PROXY=1        # обязательно, иначе перебор с любого IP заблокирует вход всем сразу
SHOME_SECURE_COOKIES=1     # только когда ходишь по https
```

`SHOME_TRUST_PROXY=1` — это число хопов, а не «да/нет». Один NPM = `1`. Ставить больше, чем
реально прокси, нельзя: тогда приложение поверит заголовку от клиента, и лимит попыток обходится.

### 4) Применить

```bash
docker compose up -d
```

### 5) Настроить Proxy Host в NPM

**Details:**

| Поле | Значение |
|---|---|
| Domain Names | `shome.home.local` (твой домен) |
| Scheme | `http` |
| Forward Hostname | `shome` (имя контейнера — работает, только если он в сети NPM) |
| Forward Port | `8080` (порт **внутри** контейнера, не `HOST_PORT`) |
| Cache Assets | можно включить |
| Block Common Exploits | можно включить |
| Websockets Support | не нужен |

Если в сеть NPM контейнер не заводил — `Forward Hostname` = IP сервера, `Forward Port` = `HOST_PORT` (`8082`).

**SSL:** выбираешь свой локальный сертификат (заливается в NPM → SSL Certificates → Add → Custom),
включаешь `Force SSL` и `HTTP/2`. `HSTS` — только если весь доступ точно по https.

**Advanced** — если будешь грузить фоны крупнее пары мегабайт:

```nginx
client_max_body_size 25m;
```

Число должно быть не меньше `SHOME_MAX_UPLOAD_MB`, иначе nginx отрежет запрос своей ошибкой `413`
раньше приложения.

Заголовки `X-Forwarded-For` / `X-Real-IP` NPM проставляет сам — руками в Advanced ничего
добавлять не надо.

### 6) Проверить, что IP клиента доходит

```bash
docker compose logs -f shome
```

Зайди на портал с телефона: в логе доступа должен быть IP телефона, а не `172.x.x.x` прокси.
Видишь адрес прокси — `SHOME_TRUST_PROXY` не применился, и один перебор заблокирует вход всем.

## Что где менять

| Что нужно | Куда лезть | Нужен ли restart |
|---|---|---|
| Настройки LDAP/AD | `config/ldap_config.json` | да |
| Порт портала | `HOST_PORT` в `.env` | `docker compose up -d` |
| Срок жизни сессии, ключ | `.env` | `docker compose up -d` |
| Попытки входа и пауза | `SHOME_LOGIN_*` в `.env` | `docker compose up -d` |
| Карточки сервисов, фон | через UI портала (или `data/App_Data/*.json`) | нет |
| Версии зависимостей | `requirements.txt` | `up -d --build` |

Конфиг LDAP читается на каждый вход, но `secret_key` и срок сессии применяются при старте:

```bash
docker compose restart      # после правки config/ldap_config.json
docker compose up -d        # после правки .env
```

## Обновление кода

```bash
git pull
cd docker && docker compose up -d --build
```

`config/` и `data/` при этом не трогаются — они не в образе.

## Бэкап

Всё ценное — два каталога:

```bash
tar czf shome-backup-$(date +%F).tar.gz docker/config docker/data
```

## Если что-то не так

**Не стартует, в логах `Permission denied` про `/data`** — `PUID`/`PGID` в `.env` не совпали
с владельцем `data/`. Проверь `ls -ln data`, поправь `.env` или сделай
`sudo chown -R $(id -u):$(id -g) data`.

**401 при входе** — смотри `docker compose logs`, текст ошибки LDAP возвращается как есть.
Частое: неверный `bind_password`, `search_filter` без `{username}`, юзер не в `required_group_dn`.

**Контейнер не видит контроллер домена** — проверь из контейнера:
`docker compose exec shome python -c "import socket; print(socket.gethostbyname('dc1.home.local'))"`.
Если DNS домена не резолвится, пропиши `dns:` в compose или используй IP в `server_uri`.

**Иконки не грузятся** — файлы должны лежать в `data/uploads/`. Пути в `services.json` вида
`/uploads/<имя>`; если переезжаешь со старой установки, перенеси туда содержимое `uploads/`.
Открытая в отдельной вкладке картинка отдаёт 401, если ты не залогинен, — так и задумано,
на самом дашборде она отрисуется.

**`429 Слишком много попыток`** — сработала защита от перебора: 10 неудачных попыток с одного IP,
затем пауза 5 минут, потом снова 10. Настраивается через `SHOME_LOGIN_MAX_ATTEMPTS` и
`SHOME_LOGIN_BLOCK_MINUTES` в `.env`. Успешный вход обнуляет счётчик; перезапуск контейнера —
тоже (счётчик в памяти процесса).

**Заблокировало всех разом** — так бывает, если портал стоит за reverse proxy: приложение видит
IP прокси, а не клиентов. Тогда `SHOME_TRUST_PROXY=1` в `.env`. Без прокси не включай: клиент
подделает `X-Forwarded-For` и обойдёт лимит.

**Загрузка отвечает `Unsupported file type`** — принимаются только картинки
(`.png .jpg .jpeg .gif .webp .svg .bmp .ico .tiff .avif .heic .heif`). Список — в `ALLOWED_UPLOAD_EXTENSIONS`
в `app.py`.

**Healthcheck красный** — `docker compose ps` покажет `unhealthy`; проверка дёргает `/login`,
так что чаще всего проблема в самом приложении, а не в LDAP.
