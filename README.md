# AmneziaVPN Telegram Bot

Telegram-бот для автоматической выдачи AmneziaWG VPN-ключей пользователям из вайтлиста.

## Возможности

- Вайтлист по Telegram-никам
- Лимит ключей на пользователя (по умолчанию 3)
- Автоматическая генерация ключей на сервере
- QR-код для импорта в AmneziaVPN
- Балансировка между серверами (наименее загруженный)
- Отзыв ключей одной командой
- Рассылка сообщений всем пользователям

## Команды для пользователей

- `/start` — проверка доступа
- `/key` — получить новый VPN-ключ
- `/mykeys` — список своих ключей
- `/help` — справка

## Команды для администратора

- `/add @username [лимит]` — добавить в вайтлист (лимит по умолчанию 3)
- `/remove @username` — убрать из вайтлиста
- `/list` — показать вайтлист
- `/servers` — статус серверов
- `/revoke @username [key_id]` — отозвать ключи
- `/broadcast текст` — рассылка всем

## Установка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/YOUR_USERNAME/amnezia-bot.git
cd amnezia-bot
```

### 2. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Настроить .env

```bash
cp .env.example .env
```

Заполнить `.env`:
- `BOT_TOKEN` — токен от @BotFather
- `ADMIN_ID` — твой Telegram user ID (узнать у @userinfobot)
- `SERVERS` — JSON-массив с конфигурацией серверов

### 4. Запустить

```bash
python bot.py
```

### 5. Запуск как сервис (systemd)

Создать `/etc/systemd/system/amnezia-bot.service`:

```ini
[Unit]
Description=AmneziaVPN Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/amnezia-bot
ExecStart=/root/amnezia-bot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Активировать:
```bash
systemctl enable amnezia-bot
systemctl start amnezia-bot
```

## Безопасность

- `.env` содержит секреты (токен бота, ключи SSH) — не коммитить
- `.env` добавлен в `.gitignore`
- SSH-ключи хранятся только на сервере, не в репозитории