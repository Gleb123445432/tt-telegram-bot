# TikTok Telegram Bot — Render Free

Версия для Render Free Web Service.

## Render

- Service: **Web Service**
- Plan: **Free**
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn bot:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/`

### Environment Variables

`BOT_TOKEN` — токен от @BotFather.

`WEBHOOK_SECRET` — можно оставить пустым, но рекомендуется задать случайную строку. Если используется Blueprint `render.yaml`, Render может сгенерировать значение автоматически.

`MAX_FILE_SIZE_MB` — `49`.

`RENDER_EXTERNAL_URL` Render предоставляет автоматически. Код использует её для установки Telegram webhook.

## Как работает

Telegram присылает обновления на `/telegram/webhook`, а приложение скачивает публичное TikTok-видео через yt-dlp и отправляет его обратно пользователю.

Временный файл удаляется после отправки. Файловое хранилище Render Free непостоянное, поэтому бот не рассчитывает на сохранение видео на диске.

## Ограничения Free

Free Web Service может автоматически засыпать после периода без входящих запросов и имеет эфемерную файловую систему. Это нормально для тестового/личного проекта.

## Inline Mode

Требование `@имябота ссылка → видео прямо в текущий чат` требует отдельной реализации с Telegram inline results и доступным media URL/кэшем. Этот архив в первую очередь делает стабильным основной сценарий: ссылка в личку боту → скачивание → видео.
