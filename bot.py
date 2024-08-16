import os
import random
import asyncio
import tempfile
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from youtube_search import YoutubeSearch
import yt_dlp

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

UPLOAD_SERVER, REPEAT_COUNT = range(2)

user_settings = {}

def search_youtube(query, min_duration=7*60, max_results=10):
    results = YoutubeSearch(query, max_results=max_results).to_dict()
    filtered_results = [
        video for video in results
        if sum(int(x) * 60 ** i for i, x in enumerate(reversed(video['duration'].split(':')))) > min_duration
    ]
    return [{'url': f"https://www.youtube.com{video['url_suffix']}", 'title': video['title']} for video in filtered_results]

async def download_audio(url):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': temp_file.name,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return temp_file.name

async def upload_file(file_path, upload_url):
    async with aiohttp.ClientSession() as session:
        with open(file_path, 'rb') as f:
            async with session.post(upload_url, data={'file': f}) as response:
                return response.status == 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Welcome! Use /settings to configure the bot.')

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Please enter the URL where you want to upload the files:')
    return UPLOAD_SERVER

async def set_upload_server(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_settings[user_id] = {'upload_url': update.message.text}
    await update.message.reply_text('Upload URL set. Now, how many times do you want to repeat the search and download process? (Enter a number)')
    return REPEAT_COUNT

async def set_repeat_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    try:
        repeat_count = int(update.message.text)
        user_settings[user_id]['repeat_count'] = repeat_count
        await update.message.reply_text(f'Settings saved. The bot will repeat the process {repeat_count} times and upload to {user_settings[user_id]["upload_url"]}')
    except ValueError:
        await update.message.reply_text('Please enter a valid number.')
        return REPEAT_COUNT
    return ConversationHandler.END

async def search_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_settings:
        await update.message.reply_text('Please use /settings to configure the bot first.')
        return

    keywords = update.message.text.split(',')
    keywords = [keyword.strip() for keyword in keywords]
    
    repeat_count = user_settings[user_id].get('repeat_count', 1)
    upload_url = user_settings[user_id].get('upload_url')

    for i in range(repeat_count):
        await update.message.reply_text(f"Iteration {i+1}/{repeat_count}")
        await update.message.reply_text(f"Searching for videos with keywords: {', '.join(keywords)}")
        
        all_videos = []
        for keyword in keywords:
            videos = search_youtube(keyword)
            all_videos.extend(videos)
        
        if not all_videos:
            await update.message.reply_text("No suitable videos found.")
            continue
        
        selected_video = random.choice(all_videos)
        await update.message.reply_text(f"Selected video: {selected_video['title']}\n{selected_video['url']}")
        
        await update.message.reply_text("Downloading audio... This may take a while.")
        
        try:
            audio_file = await download_audio(selected_video['url'])
            await update.message.reply_audio(audio=open(audio_file, 'rb'), title=selected_video['title'])
            
            if upload_url:
                await update.message.reply_text(f"Uploading to {upload_url}...")
                if await upload_file(audio_file, upload_url):
                    await update.message.reply_text("Upload successful")
                else:
                    await update.message.reply_text("Upload failed")
            
            os.remove(audio_file)  # Clean up the temporary file
        except Exception as e:
            await update.message.reply_text(f"An error occurred: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await search_and_send(update, context)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('settings', settings)],
        states={
            UPLOAD_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_upload_server)],
            REPEAT_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_repeat_count)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()