import asyncio
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message, Update

TOKEN = os.getenv("BOT_TOKEN")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "49"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024
PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is not set")

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)
dp = Dispatcher()


def is_tiktok_url(url: str) -> bool:
    return "tiktok.com/" in url.lower()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я скачиваю публичные видео из TikTok.\n\n"
        "Просто отправь мне ссылку на ролик."
    )


@dp.message(F.text)
async def handle_link(message: Message):
    url = message.text.strip()
    if not is_tiktok_url(url):
        await message.answer("❌ Пришли ссылку на TikTok.")
        return

    status = await message.answer("⏳ Скачиваю видео…")
    tmpdir = Path(tempfile.mkdtemp(prefix="ttbot_"))
    try:
        output = tmpdir / "video.%(ext)s"
        options = {
            "outtmpl": str(output),
            # Prefer a single MP4 file so Free Web Service does not need apt/ffmpeg.
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "socket_timeout": 30,
        }

        def download():
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])

        await asyncio.to_thread(download)
        videos = [
            p for p in tmpdir.iterdir()
            if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
        ]
        if not videos:
            raise RuntimeError("video not found")

        video = videos[0]
        if video.stat().st_size > MAX_FILE_SIZE:
            await status.edit_text(
                f"❌ Файл больше лимита Telegram для этого бота ({MAX_FILE_SIZE_MB} МБ)."
            )
            return

        await status.edit_text("📤 Отправляю…")
        await message.answer_video(
            video=FSInputFile(video),
            caption="Готово ✅",
            supports_streaming=True,
        )
        await status.delete()
    except Exception:
        logging.exception("TikTok download failed")
        await status.edit_text(
            "❌ Не удалось скачать это видео. Проверь ссылку и попробуй ещё раз."
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram/webhook"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logging.info("Telegram webhook set to %s", webhook_url)
    yield
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()


app = FastAPI(title="TikTok Telegram Bot", lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != WEBHOOK_SECRET:
            return {"ok": False}

    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}
