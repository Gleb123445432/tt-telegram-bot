import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

TOKEN = os.getenv("BOT_TOKEN")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "49"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Привет! Я скачиваю публичные видео из TikTok.\n\n"
        "Просто отправь мне ссылку на ролик."
    )

@dp.message(F.text)
async def handle_link(message: Message):
    url = message.text.strip()
    if "tiktok.com" not in url:
        await message.answer("❌ Пришли ссылку на TikTok.")
        return

    status = await message.answer("⏳ Скачиваю видео…")
    tmpdir = Path(tempfile.mkdtemp(prefix="ttbot_"))
    try:
        output = tmpdir / "video.%(ext)s"
        options = {
            "outtmpl": str(output),
            "format": "best[ext=mp4]/best",
            "merge_output_format": "mp4",
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
        videos = [p for p in tmpdir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not videos:
            raise RuntimeError("video not found")

        video = videos[0]
        if video.stat().st_size > MAX_FILE_SIZE:
            await status.edit_text(f"❌ Файл больше лимита Telegram для этого бота ({MAX_FILE_SIZE_MB} МБ).")
            return

        await status.edit_text("📤 Отправляю…")
        await message.answer_video(video=FSInputFile(video), caption="Готово ✅")
        await status.delete()
    except Exception:
        logging.exception("TikTok download failed")
        await status.edit_text("❌ Не удалось скачать это видео. Проверь ссылку и попробуй ещё раз.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
