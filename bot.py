import asyncio
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    FSInputFile,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultVideo,
    InputTextMessageContent,
    Message,
)
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

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
    return m.group(0).rstrip(".,!?)[]}>\"" + "'")


def tikwm_info(url: str) -> dict:
    r = requests.post(
        "https://www.tikwm.com/api/",
        data={"url": url, "hd": "1"},
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
        },
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0 or not data.get("data"):
        raise RuntimeError(data.get("msg", "TikWM returned an error"))
    return data["data"]


def download_video(url: str, output_dir: str) -> tuple[str, dict]:
    info = tikwm_info(url)
    video_url = info.get("hdplay") or info.get("play")
    if not video_url:
        raise RuntimeError("No video URL returned")

    filename = Path(output_dir) / f"{info.get('id', uuid.uuid4().hex)}.mp4"
    with requests.get(
        video_url,
        headers={"User-Agent": "Mozilla/5.0"},
        stream=True,
        timeout=60,
    ) as r:
        r.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)
    return str(filename), info


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Привет! 👋\n\n"
        "1) Пришли ссылку TikTok сюда — я отправлю видео.\n"
        "2) В любом чате напиши:\n"
        "@имя_бота https://www.tiktok.com/...\n\n"
        "и выбери видео из результата."
    )


@dp.message(F.text)
async def private_tiktok_handler(message: Message):
    url = clean_url(message.text)
    if not url:
        await message.answer("Пришли ссылку на TikTok.")
        return

    status = await message.answer("⏳ Скачиваю видео…")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        try:
            filename, info = await asyncio.to_thread(download_video, url, tmp)
            path = Path(filename)
            size_mb = path.stat().st_size / (1024 * 1024)

            if size_mb > MAX_FILE_SIZE_MB:
                await status.edit_text(
                    f"❌ Видео весит {size_mb:.1f} МБ, лимит — {MAX_FILE_SIZE_MB} МБ."
                )
                return

            await message.answer_video(
                video=FSInputFile(path),
                caption="✅ Готово",
                supports_streaming=True,
            )
            await status.delete()
        except Exception:
            logger.exception("Private TikTok download failed")
            await status.edit_text(
                "❌ Не удалось скачать это видео. Попробуй другую ссылку."
            )


@dp.inline_query()
async def inline_handler(query: InlineQuery):
    url = clean_url(query.query)
    if not url:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="help",
                    title="Вставь ссылку на TikTok",
                    description="@бот https://www.tiktok.com/...",
                    input_message_content=InputTextMessageContent(
                        message_text="Вставь ссылку на TikTok после имени бота."
                    ),
                )
            ],
            cache_time=1,
            is_personal=True,
        )
        return

    try:
        # TikWM returns a public CDN video URL and cover image.
        info = await asyncio.to_thread(tikwm_info, url)
        video_url = info.get("hdplay") or info.get("play")
        cover_url = info.get("cover") or info.get("origin_cover")

        if not video_url or not cover_url:
            raise RuntimeError("TikWM did not return video/cover URLs")

        video_id = str(info.get("id") or uuid.uuid4().hex)
        title = "TikTok video"
        author = info.get("author") or {}
        if isinstance(author, dict) and author.get("nickname"):
            title = f"TikTok — {author['nickname']}"

        result = InlineQueryResultVideo(
            id=video_id,
            title=title,
            video_url=video_url,
            mime_type="video/mp4",
            thumbnail_url=cover_url,
            caption="",
        )

        await query.answer(
            [result],
            cache_time=1,
            is_personal=True,
        )

    except Exception:
        logger.exception("Inline TikTok failed")
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="error",
                    title="Не удалось получить видео",
                    description="Попробуй ещё раз через несколько секунд.",
                    input_message_content=InputTextMessageContent(
                        message_text="Не удалось получить видео TikTok. Попробуй ещё раз."
                    ),
                )
            ],
            cache_time=1,
            is_personal=True,
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
