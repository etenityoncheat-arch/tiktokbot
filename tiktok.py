import os
import asyncio
from typing import Union
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
import requests
from urllib.parse import urlparse, quote
import re
import json
from bs4 import BeautifulSoup
import aiohttp
import uuid

# Initialize bot with your token
API_TOKEN = '8149075650:AAGACk7w1li4gRIg-buzpGik7q3g6mCzO6k'
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Emojis for better visual appearance
WELCOME_EMOJI = "👋"
VIDEO_EMOJI = "🎥"
MUSIC_EMOJI = "🎵"
PHOTO_EMOJI = "📸"
LOADING_EMOJI = "⌛"
ERROR_EMOJI = "❌"
SUCCESS_EMOJI = "✅"

# Headers for requests
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

async def download_tiktok(url: str) -> dict:
    """Download TikTok video, audio or images and return media info using tikwm.com API"""
    try:
        api_url = "https://tikwm.com/api/"
        params = {"url": url, "hd": 1}
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0 and 'data' in data:
                        d = data['data']
                        video_url = d.get('download') or d.get('play')
                        audio_url = d.get('music', '')
                        thumbnail = d.get('cover', '')
                        images = d.get('images', [])  # <-- добавлено
                        return {
                            'video_url': video_url,
                            'audio_url': audio_url,
                            'thumbnail': thumbnail,
                            'images': images
                        }
                    else:
                        raise Exception(data.get('msg', 'Unknown error from API'))
                else:
                    raise Exception(f"API returned status {response.status}")
    except asyncio.TimeoutError:
        raise Exception("API timeout. Please try again later.")
    except Exception as e:
        raise Exception(f"Download error: {str(e)}")

@dp.message(Command("start"))
async def start_command(message: Message):
    welcome_text = (
        f"{WELCOME_EMOJI} *Welcome to TikTok Downloader Bot\!*\n\n"
        f"I can help you download:\n"
        f"{VIDEO_EMOJI} Videos\n"
        f"{MUSIC_EMOJI} Audio\n"
        f"{PHOTO_EMOJI} Photos\n\n"
        "Just send me a TikTok link\!"
    )
    await message.answer(welcome_text, parse_mode="MarkdownV2")

# Временное хранилище для ссылок (очистка не реализована, для продакшена лучше использовать БД или TTL dict)
DOWNLOAD_CACHE = {}

@dp.message()
async def handle_tiktok_url(message: Message):
    url = message.text.strip()
    # поддержка /start <url> для автозапуска из inline
    if url.startswith("/start "):
        url = url[7:].strip()
    tiktok_patterns = [
        r'https?://(?:www\.)?tiktok\.com/.*',
        r'https?://(?:vm|vt)\.tiktok\.com/.*',
        r'https?://.*\.tiktok\.com/.*'
    ]
    if not any(re.match(pattern, url) for pattern in tiktok_patterns):
        await message.reply(
            f"{ERROR_EMOJI} Please send a valid TikTok link!"
        )
        return

    loading_msg = await message.reply(LOADING_EMOJI)

    try:
        # Handle TikTok short URLs
        if 'vm.tiktok.com' in url or 'vt.tiktok.com' in url:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    url = str(response.url)

        content = await download_tiktok(url)
        if not content.get('video_url'):
            raise Exception("Could not extract video URL")

        # Генерируем уникальный ключ и сохраняем ссылки
        unique_id = str(uuid.uuid4())
        DOWNLOAD_CACHE[unique_id] = content

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{VIDEO_EMOJI} Download Video", callback_data=f"video_{unique_id}"),
            ]
        ])
        if content.get('audio_url'):
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"{MUSIC_EMOJI} Download Audio", callback_data=f"audio_{unique_id}")
            ])
        if content.get('images'):  # <-- добавлено
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"{PHOTO_EMOJI} Download Photo(s)", callback_data=f"photo_{unique_id}")
            ])

        try:
            await loading_msg.delete()
        except Exception:
            pass

        await message.reply(
            f"{SUCCESS_EMOJI} Choose what you want to download:",
            reply_markup=keyboard
        )

    except Exception as e:
        try:
            await loading_msg.delete()
        except Exception:
            pass
        error_message = str(e) if "Download error" in str(e) else "An error occurred while processing your request"
        await message.reply(f"{ERROR_EMOJI} {error_message}")

@dp.callback_query()
async def process_callback(callback_query: types.CallbackQuery):
    action, unique_id = callback_query.data.split('_', 1)
    content = DOWNLOAD_CACHE.get(unique_id)
    if not content:
        await callback_query.message.reply(f"{ERROR_EMOJI} Download link expired. Please try again.")
        return

    try:
        loading_msg = await callback_query.message.reply(LOADING_EMOJI)

        url = content['video_url'] if action == "video" else content['audio_url']
        filename = 'temp_video.mp4' if action == "video" else 'temp_audio.mp3'

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                file_content = await response.read()
                with open(filename, 'wb') as f:
                    f.write(file_content)

        if action == "video":
            await callback_query.message.reply_video(
                video=FSInputFile(filename),
                caption=f"{SUCCESS_EMOJI} Here's your video!"
            )
        elif action == "audio":
            await callback_query.message.reply_audio(
                audio=FSInputFile(filename),
                caption=f"{SUCCESS_EMOJI} Here's your audio!"
            )
        elif action == "photo":
            images = content.get('images', [])
            if not images:
                await callback_query.message.reply(f"{ERROR_EMOJI} No images found.")
            else:
                media = []
                temp_files = []
                for idx, img_url in enumerate(images):
                    img_name = f"temp_img_{unique_id}_{idx}.jpg"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(img_url) as resp:
                            img_bytes = await resp.read()
                            if not img_bytes or len(img_bytes) < 1024:  # меньше 1Кб — считаем битым
                                continue
                            with open(img_name, 'wb') as f:
                                f.write(img_bytes)
                    if os.path.exists(img_name) and os.path.getsize(img_name) > 0:
                        temp_files.append(img_name)
                        media.append(types.InputMediaPhoto(media=FSInputFile(img_name)))
                if not media:
                    await callback_query.message.reply(f"{ERROR_EMOJI} No valid images found.")
                elif len(media) == 1:
                    await callback_query.message.reply_photo(
                        photo=FSInputFile(temp_files[0]),
                        caption=f"{SUCCESS_EMOJI} Here's your photo!"
                    )
                else:
                    await callback_query.message.reply_media_group(media=media)
                for f in temp_files:
                    os.remove(f)

        os.remove(filename)

        try:
            await loading_msg.delete()
        except Exception:
            pass
        await callback_query.answer()

    except Exception as e:
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await callback_query.message.reply(f"{ERROR_EMOJI} Download failed: {str(e)}")

@dp.inline_query()
async def inline_tiktok_handler(inline_query: types.InlineQuery):
    url = inline_query.query.strip()
    tiktok_patterns = [
        r'https?://(?:www\.)?tiktok\.com/.*',
        r'https?://(?:vm|vt)\.tiktok\.com/.*',
        r'https?://.*\.tiktok\.com/.*'
    ]
    if not any(re.match(pattern, url) for pattern in tiktok_patterns):
        await bot.answer_inline_query(
            inline_query.id,
            results=[],
            cache_time=1,
            switch_pm_text="Send me a TikTok link!",
            switch_pm_parameter="start"
        )
        return

    try:
        content = await download_tiktok(url)
        thumb_url = content.get('thumbnail') or (content.get('images') or [None])[0]
        title = "TikTok Video" if content.get('video_url') else "TikTok Photo"
        description = "Нажмите, чтобы скачать через бота в ЛС"

        result = types.InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            thumb_url=thumb_url,
            input_message_content=types.InputTextMessageContent(
                message_text=f"{url}"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Скачать через бота", url=f"https://t.me/{(await bot.me()).username}?start={quote(url)}")]
            ])
        )
        await bot.answer_inline_query(
            inline_query.id,
            results=[result],
            cache_time=1
        )
    except Exception:
        await bot.answer_inline_query(
            inline_query.id,
            results=[],
            cache_time=1,
            switch_pm_text="Ошибка! Попробуйте позже.",
            switch_pm_parameter="start"
        )

async def main():
    # Start the bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())