import asyncio
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import requests
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

TIKTOK_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com|tiktokv\.com)/\S+",
    re.I,
)

def clean_url(text: str) -> str | None:
    m = TIKTOK_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,!?)[]}>\"'")


def download_from_tikwm(url: str, output_dir: str) -> tuple[str, dict]:
    """
    Uses TikWM's public API as the primary TikTok extractor.
    This avoids the current TikTok webpage challenge affecting yt-dlp.
    """
    api_url = "https://www.tikwm.com/api/"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    }

    response = requests.post(
        api_url,
        data={"url": url, "hd": "1"},
        headers=headers,
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != 0 or not data.get("data"):
        raise RuntimeError(f"TikWM error: {data.get('msg', 'unknown error')}")

    info = data["data"]
    video_url = info.get("hdplay") or info.get("play")
    if not video_url:
        raise RuntimeError("TikWM did not return a video URL")

    filename = Path(output_dir) / f"{info.get('id', 'tiktok')}.mp4"

    with requests.get(
        video_url,
        headers=headers,
        stream=True,
        timeout=60,
    ) as video_response:
        video_response.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in video_response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

    return str(filename), info


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "Пришли ссылку на TikTok — я скачаю видео и отправлю его сюда."
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
            filename, info = await asyncio.to_thread(
                download_from_tikwm, url, tmp
            )

            path = Path(filename)
            if not path.exists():
                raise FileNotFoundError("Downloaded file was not found")

            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                await status.edit_text(
                    f"❌ Видео весит {size_mb:.1f} МБ. "
                    f"Лимит бота установлен на {MAX_FILE_SIZE_MB} МБ."
                )
                return

            await message.answer_video(
                video=FSInputFile(path),
                caption="✅ Готово",
                supports_streaming=True,
            )
            await status.delete()

        except Exception:
            logger.exception("TikTok download failed")
            await status.edit_text(
                "❌ Не удалось скачать это видео. "
                "Попробуй ещё раз через несколько секунд или другую ссылку."
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
