# TikTok Telegram Bot

Telegram-бот, который принимает публичную ссылку TikTok, скачивает видео через yt-dlp и отправляет его обратно в Telegram.

## Быстрый запуск

1. Создай бота через @BotFather и получи токен.
2. Скопируй `.env.example` в `.env` и укажи `BOT_TOKEN`.
3. Запусти Docker Compose:

```bash
docker compose up -d --build
```

## Локальный запуск

Нужен Python 3.12+ и FFmpeg.

```bash
pip install -r requirements.txt
python bot.py
```

Бот рассчитан на публично доступные материалы, которые пользователь имеет право скачивать.
