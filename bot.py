import asyncio
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "49"))

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is not available")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

TIKTOK_RE = re.compile(r"https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com|tiktokv\.com)/\S+", re.I)


def clean_url(text: str) -> str | None:
    match = TIKTOK_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?)[]}>\"'")


def download_tiktok(url: str, output_dir: str) -> tuple[str, dict]:
    # yt-dlp 2026.08.19 fixed the current TikTok challenge/web extraction issue.
    # Keep the format MP4-compatible and avoid requiring a merge when possible.
    opts = {
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename, info


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "Пришли мне ссылку на TikTok — я попробую скачать видео и отправить его сюда."
    )


@dp.message(F.text)
async def tiktok_handler(message: Message):
    url = clean_url(message.text)
    if not url:
        await message.answer("Пришли ссылку на TikTok.")
        return

    status = await message.answer("⏳ Скачиваю видео…")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            filename, info = await asyncio.to_thread(download_tiktok, url, tmp)
            path = Path(filename)

            if not path.exists():
                # Some extractors can choose a different extension.
                files = list(Path(tmp).glob("*"))
                if not files:
                    raise FileNotFoundError("Downloaded file was not found")
                path = files[0]

            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                await status.edit_text(
                    f"❌ Видео скачалось, но его размер {size_mb:.1f} МБ — "
                    f"это больше установленного лимита {MAX_FILE_SIZE_MB} МБ."
                )
                return

            caption = "✅ Готово"
            await message.answer_video(
                video=FSInputFile(path),
                caption=caption,
                supports_streaming=True,
            )
            await status.delete()

        except Exception:
            logger.exception("TikTok download failed")
            await status.edit_text(
                "❌ Не удалось скачать это видео. "
                "Попробуй другую ссылку TikTok."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram/webhook"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info("Telegram webhook set: %s", webhook_url)
    try:
        yield
    finally:
        await bot.delete_webhook()
        await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(update: dict):
    from aiogram.types import Update
    telegram_update = Update.model_validate(update)
    await dp.feed_update(bot, telegram_update)
    return {"ok": True}
