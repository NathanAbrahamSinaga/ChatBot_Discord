import os
import base64
import asyncio
import io
import time
import logging
from dotenv import load_dotenv
from discord import Client, Intents, Interaction, app_commands, Attachment, ButtonStyle, ui, Embed, Color
from discord.ext import commands
import google.genai as genai
import google.genai.types as types
from bs4 import BeautifulSoup
import aiohttp
from typing import Optional, Dict, List, Tuple
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

required_env_vars = ['GEMINI_API_KEY', 'DISCORD_TOKEN', 'GOOGLE_API_KEY', 'GOOGLE_CSE_ID']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
    exit(1)

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

system_prompt = """
Jawab dengan bahasa Indonesia. Pastikan output rapi dan mudah dibaca di Discord menggunakan format Markdown:
- Gunakan # untuk heading besar, ## untuk subheading.
- Gunakan - untuk bullet point pada list.
- Gunakan ** untuk teks tebal, * untuk italic.
- Gunakan ``` untuk blok kode (contoh: ```python).
- Pisahkan paragraf dengan baris kosong.
- Batasi pesan agar tidak melebihi 2000 karakter.
- Jika ada tautan GIF dari Tenor, jangan analisis kontennya, tetapi respon seperti manusia biasa dengan nada ramah dan santai, misalnya "Haha, GIF-nya lucu banget, makasih ya!" atau sesuai konteks.
"""

class BotState:
    def __init__(self):
        self.conversation_history: Dict[str, any] = {}
        self.command_cooldowns: Dict[str, float] = {}
        self.channel_activity: Dict[str, bool] = {}
        self.last_activity: Dict[str, float] = {}
        self.last_button_message: Dict[str, any] = {}

    def cleanup_old_data(self):
        current_time = time.time()
        expired_cooldowns = [
            key for key, timestamp in self.command_cooldowns.items()
            if current_time > timestamp
        ]
        for key in expired_cooldowns:
            del self.command_cooldowns[key]

bot_state = BotState()

COOLDOWN_TIME = 30
MAX_FILE_SIZE = 25 * 1024 * 1024
INACTIVITY_TIMEOUT = 600

SUPPORTED_MIME_TYPES = {
    'image/jpeg': 'image',
    'image/png': 'image',
    'image/gif': 'image',
    'application/pdf': 'pdf',
    'video/mp4': 'video',
    'video/mpeg': 'video',
    'audio/mp3': 'audio',
    'audio/mpeg': 'audio',
    'audio/wav': 'audio',
    'image/jpg': 'image'
}

http_session: Optional[aiohttp.ClientSession] = None

async def get_http_session() -> aiohttp.ClientSession:
    global http_session
    if http_session is None or http_session.closed:
        timeout = aiohttp.ClientTimeout(total=30)
        http_session = aiohttp.ClientSession(timeout=timeout)
    return http_session

async def fetch_web_content(url: str) -> str:
    try:
        session = await get_http_session()
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; DiscordBot/1.0)'}
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return f"**Error Scraping**\nHTTP {response.status}: Gagal mengambil konten dari {url}."
            html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        content = ""
        for elem in soup.select('p, h1, h2, h3, article, main'):
            text = elem.get_text().strip()
            if text:
                content += text + '\n'
        return content[:5000] if content else "Konten tidak ditemukan pada halaman tersebut."
    except asyncio.TimeoutError:
        logger.error(f'Timeout error fetching {url}')
        return f"**Error Scraping**\nTimeout saat mengambil konten dari {url}."
    except Exception as error:
        logger.error(f'Error di fetchWebContent: {error}')
        return f"**Error Scraping**\nGagal mengambil konten dari {url}: {str(error)}"

async def google_search(query: str) -> str:
    try:
        session = await get_http_session()
        url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={query}&num=5&lr=lang_id&gl=id"
        async with session.get(url) as response:
            if response.status != 200:
                return f"**Error**\nGoogle Search API error: {response.status}"
            data = await response.json()
        if not data.get('items'):
            return "**Hasil Pencarian**\nMaaf, tidak ada hasil yang ditemukan untuk pencarian ini."
        first_url = data['items'][0]['link']
        web_content = await fetch_web_content(first_url)
        search_results = "**Hasil Pencarian dari Google**\n\n"
        for index, item in enumerate(data['items']):
            title = item.get('title', 'No Title')[:100]
            snippet = item.get('snippet', 'No description')[:200]
            search_results += f"- **{index + 1}. {title}**\n"
            search_results += f"  {snippet}\n"
            search_results += f"  Sumber: [Klik di sini]({item['link']})\n\n"
        search_results += f"**Konten dari {first_url}**\n{web_content}\n"
        return search_results
    except Exception as error:
        logger.error(f'Error di googleSearch: {error}')
        return "**Error**\nTerjadi kesalahan saat melakukan pencarian Google."

def extract_youtube_url(text: str) -> Optional[str]:
    youtube_patterns = [
        r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)',
        r'(https?://youtu\.be/[\w-]+)',
        r'(https?://(?:www\.)?youtube\.com/embed/[\w-]+)'
    ]
    for pattern in youtube_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def extract_tenor_url(text: str) -> Optional[str]:
    tenor_pattern = r'(https?://tenor\.com/view/[\w-]+)'
    match = re.search(tenor_pattern, text)
    return match.group(0) if match else None

async def generate_response(channel_id: str, prompt: str, media_data: Optional[Dict] = None,
                           search_query: Optional[str] = None, use_thinking: bool = False,
                           youtube_url: Optional[str] = None, tenor_url: Optional[str] = None) -> str:
    try:
        model_name = "gemini-2.5-pro" if use_thinking else "gemini-2.5-flash"
        if channel_id not in bot_state.conversation_history:
            bot_state.conversation_history[channel_id] = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.9,
                    max_output_tokens=4000))
        chat = bot_state.conversation_history[channel_id]
        contents = [prompt]
        if search_query:
            search_results = await google_search(search_query)
            contents.append(search_results)
        if media_data:
            if media_data['mime_type'] == 'application/pdf':
                pdf_buffer = base64.b64decode(media_data['base64'])
                if len(pdf_buffer) > MAX_FILE_SIZE:
                    return "**Error**\nFile PDF terlalu besar. Maksimal 25MB."
                pdf_file = client.files.upload(
                    file=io.BytesIO(pdf_buffer),
                    config=dict(mime_type='application/pdf'))
                contents.append(pdf_file)
            else:
                file_data = base64.b64decode(media_data['base64'])
                if len(file_data) > MAX_FILE_SIZE:
                    return "**Error**\nFile terlalu besar. Maksimal 25MB."
                contents.append(
                    types.Part.from_bytes(
                        data=file_data, mime_type=media_data['mime_type']))
        if youtube_url:
            contents.append(
                types.Part(file_data=types.FileData(file_uri=youtube_url)))
        if tenor_url:
            contents.append(tenor_url)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: chat.send_message(contents))
        response_text = response.text
        if not any(marker in response_text for marker in ['#', '-', '```']):
            paragraphs = [p.strip() for p in response_text.split('\n\n') if p.strip()]
            response_text = '\n\n' + '\n\n'.join(paragraphs)
        return response_text
    except asyncio.TimeoutError:
        return "**Error**\nTimeout: Permintaan memakan waktu terlalu lama."
    except Exception as error:
        logger.error(f'Error di generateResponse: {error}')
        return f"**Error**\nTerjadi kesalahan saat menghasilkan respons: {str(error)}"

def split_text(text: str, max_length: int = 1900) -> List[str]:
    if len(text) <= max_length:
        return [text]
    chunks = []
    current_chunk = ''
    lines = text.split('\n')
    in_code_block = False
    current_language = ''
    for line in lines:
        line_with_newline = line + '\n' if line != lines[-1] else line
        if line.strip().startswith('```'):
            if not in_code_block:
                current_language = line.strip().replace('```', '')
                in_code_block = True
            else:
                in_code_block = False
            if len(current_chunk) + len(line_with_newline) > max_length:
                if in_code_block:
                    current_chunk += '\n```'
                chunks.append(current_chunk.strip())
                current_chunk = line_with_newline
            else:
                current_chunk += line_with_newline
            continue
        if len(line) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ''
            for i in range(0, len(line), max_length):
                part = line[i:i + max_length]
                chunks.append(part)
        else:
            if len(current_chunk) + len(line_with_newline) > max_length:
                if in_code_block:
                    current_chunk += '\n```'
                chunks.append(current_chunk.strip())
                current_chunk = f"```{current_language}\n" if in_code_block else ""
                current_chunk += line_with_newline
            else:
                current_chunk += line_with_newline
    if current_chunk.strip():
        if in_code_block and not current_chunk.endswith('```'):
            current_chunk += '\n```'
        chunks.append(current_chunk.strip())
    return [chunk for chunk in chunks if chunk.strip()]

def check_cooldown(user_id: str, command: str) -> Tuple[bool, float]:
    cooldown_key = f"{user_id}-{command}"
    current_time = time.time()
    cooldown_end_time = bot_state.command_cooldowns.get(cooldown_key, 0)
    if current_time < cooldown_end_time:
        remaining_time = cooldown_end_time - current_time
        return True, remaining_time
    bot_state.command_cooldowns[cooldown_key] = current_time + COOLDOWN_TIME
    return False, 0

class InteractionButtons(ui.View):
    def __init__(self, channel_id: str):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @ui.button(label="New", style=ButtonStyle.green, custom_id="new_conversation")
    async def new_button(self, interaction: Interaction, button: ui.Button):
        channel_id = str(interaction.channel_id)
        if channel_id in bot_state.conversation_history:
            bot_state.conversation_history.pop(channel_id)
        bot_state.channel_activity[channel_id] = True
        bot_state.last_activity[channel_id] = time.time()
        if channel_id in bot_state.last_button_message:
            try:
                await bot_state.last_button_message[channel_id].delete()
                del bot_state.last_button_message[channel_id]
            except Exception as e:
                logger.error(f"Error deleting button message: {e}")
        embed = Embed(
            description="✅ Percakapan baru telah dimulai! Kirim pesan untuk melanjutkan.",
            color=Color.green())
        await interaction.response.send_message(embed=embed)

    @ui.button(label="Continue", style=ButtonStyle.blurple, custom_id="continue_conversation")
    async def continue_button(self, interaction: Interaction, button: ui.Button):
        channel_id = str(interaction.channel_id)
        bot_state.channel_activity[channel_id] = True
        bot_state.last_activity[channel_id] = time.time()
        if channel_id in bot_state.last_button_message:
            try:
                await bot_state.last_button_message[channel_id].delete()
                del bot_state.last_button_message[channel_id]
            except Exception as e:
                logger.error(f"Error deleting button message: {e}")
        embed = Embed(
            description="✅ Melanjutkan percakapan! Kirim pesan untuk melanjutkan.",
            color=Color.blurple())
        await interaction.response.send_message(embed=embed)

intents = Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f'Bot {bot.user} siap!')
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
        bot.loop.create_task(periodic_cleanup())
        bot.loop.create_task(check_inactivity())
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

async def check_inactivity():
    while True:
        await asyncio.sleep(5)
        current_time = time.time()
        for channel_id in list(bot_state.channel_activity):
            if bot_state.channel_activity.get(channel_id, False):
                last_activity = bot_state.last_activity.get(channel_id, 0)
                if current_time - last_activity > INACTIVITY_TIMEOUT:
                    if channel_id not in bot_state.last_button_message:
                        channel = bot.get_channel(int(channel_id))
                        if channel:
                            embed = Embed(
                                title="Bot Tidak Aktif",
                                description="Bot telah tidak aktif selama 10 menit. Pilih opsi di bawah untuk melanjutkan:",
                                color=Color.blue())
                            view = InteractionButtons(channel_id)
                            message = await channel.send(embed=embed, view=view)
                            bot_state.last_button_message[channel_id] = message
        await asyncio.sleep(5)

async def periodic_cleanup():
    while True:
        await asyncio.sleep(300)
        bot_state.cleanup_old_data()
        logger.info("Performed periodic cleanup")

@bot.tree.command(name="activate", description="Mengaktifkan bot di channel ini")
async def activate(interaction: Interaction):
    user_id = str(interaction.user.id)
    channel_id = str(interaction.channel_id)
    on_cooldown, remaining_time = check_cooldown(user_id, "activate")
    if on_cooldown:
        await interaction.response.send_message(
            f"**Cooldown**\nSilakan tunggu {remaining_time:.1f} detik sebelum menggunakan perintah ini lagi.",
            ephemeral=True)
        return
    bot_state.channel_activity[channel_id] = True
    bot_state.last_activity[channel_id] = time.time()
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e:
            logger.error(f"Error deleting button message: {e}")
    await interaction.response.send_message("**Status**\nBot diaktifkan di channel ini!")

@bot.tree.command(name="deactivate", description="Menonaktifkan bot di channel ini")
async def deactivate(interaction: Interaction):
    user_id = str(interaction.user.id)
    channel_id = str(interaction.channel_id)
    on_cooldown, remaining_time = check_cooldown(user_id, "deactivate")
    if on_cooldown:
        await interaction.response.send_message(
            f"**Cooldown**\nSilakan tunggu {remaining_time:.1f} detik sebelum menggunakan perintah ini lagi.",
            ephemeral=True)
        return
    bot_state.channel_activity[channel_id] = False
    if channel_id in bot_state.last_activity:
        del bot_state.last_activity[channel_id]
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e:
            logger.error(f"Error deleting button message: {e}")
    await interaction.response.send_message("**Status**\nBot dinonaktifkan di channel ini!")

async def download_attachment(attachment: Attachment) -> Optional[bytes]:
    try:
        if attachment.size > MAX_FILE_SIZE:
            return None
        session = await get_http_session()
        async with session.get(attachment.url) as response:
            if response.status == 200:
                return await response.read()
        return None
    except Exception as e:
        logger.error(f'Error downloading attachment: {e}')
        return None

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    channel_id = str(message.channel.id)
    is_bot_active = bot_state.channel_activity.get(channel_id, False)
    content = message.content.strip()
    user_id = str(message.author.id)
    current_time = time.time()
    user_last_message = bot_state.command_cooldowns.get(f"{user_id}-message", 0)
    if current_time - user_last_message < 2:
        return
    bot_state.command_cooldowns[f"{user_id}-message"] = current_time
    bot_state.last_activity[channel_id] = current_time
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e:
            logger.error(f"Error deleting button message: {e}")
    if content.lower() == '!reset':
        if channel_id in bot_state.conversation_history:
            bot_state.conversation_history.pop(channel_id)
            await message.channel.send('✅ Riwayat percakapan di channel ini telah direset!')
        else:
            await message.channel.send('ℹ️ Tidak ada riwayat percakapan yang perlu dihapus')
        return
    if content.lower().startswith('!think'):
        async with message.channel.typing():
            thinking_prompt = content.replace('!think', '', 1).strip()
            if not thinking_prompt:
                await message.reply('**Error**\nGunakan format: `!think [pertanyaan atau permintaan]`')
                return
            attachment = message.attachments[0] if message.attachments else None
            media_data = None
            if attachment:
                mime_type = attachment.content_type
                if mime_type not in SUPPORTED_MIME_TYPES:
                    supported_formats = ', '.join(set(SUPPORTED_MIME_TYPES.keys()))
                    await message.reply(
                        f'**Error**\nFormat file tidak didukung.\n**Format yang didukung:** {supported_formats}')
                    return
                file_data = await download_attachment(attachment)
                if file_data is None:
                    await message.reply(
                        '**Error**\nGagal mengunduh file atau file terlalu besar (maksimal 25MB)!')
                    return
                base64_data = base64.b64encode(file_data).decode('utf-8')
                media_data = {'mime_type': mime_type, 'base64': base64_data}
            try:
                ai_response = await generate_response(channel_id, thinking_prompt, media_data, None, True)
                response_chunks = split_text(ai_response)
                for i, chunk in enumerate(response_chunks):
                    await message.channel.send(chunk)
                    if i < len(response_chunks) - 1:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f'Error in think command: {e}')
                await message.channel.send(
                    "**Error**\nTerjadi kesalahan saat memproses permintaan thinking.")
        return
    if content.lower().startswith('!gift'):
        async with message.channel.typing():
            gift_prompt = content.replace('!gift', '', 1).strip()
            if not gift_prompt:
                await message.reply('**Error**\nGunakan format: `!gift [pertanyaan atau permintaan]`')
                return
            attachment = message.attachments[0] if message.attachments else None
            media_data = None
            tenor_url = extract_tenor_url(content)
            if attachment:
                mime_type = attachment.content_type
                if mime_type not in SUPPORTED_MIME_TYPES:
                    supported_formats = ', '.join(set(SUPPORTED_MIME_TYPES.keys()))
                    await message.reply(
                        f'**Error**\nFormat file tidak didukung.\n**Format yang didukung:** {supported_formats}')
                    return
                file_data = await download_attachment(attachment)
                if file_data is None:
                    await message.reply(
                        '**Error**\nGagal mengunduh file atau file terlalu besar (maksimal 25MB)!')
                    return
                base64_data = base64.b64encode(file_data).decode('utf-8')
                media_data = {'mime_type': mime_type, 'base64': base64_data}
            try:
                ai_response = await generate_response(channel_id, gift_prompt, media_data, None, False, None, tenor_url)
                response_chunks = split_text(ai_response)
                for i, chunk in enumerate(response_chunks):
                    await message.channel.send(chunk)
                    if i < len(response_chunks) - 1:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f'Error in gift command: {e}')
                await message.channel.send("**Error**\nTerjadi kesalahan saat memproses permintaan.")
        return
    if is_bot_active or content.startswith('!chat') or content.startswith('!cari'):
        prompt = content
        search_query = None
        youtube_url = extract_youtube_url(content)
        tenor_url = extract_tenor_url(content)
        if content.startswith('!cari'):
            search_query = content.replace('!cari', '', 1).strip()
            if not search_query:
                await message.reply('**Error**\nGunakan format: `!cari [kata kunci pencarian]`')
                return
            prompt = f"Berikan jawaban berdasarkan pencarian untuk: {search_query}"
        elif content.startswith('!chat'):
            chat_prompt = content.replace('!chat', '', 1).strip()
            if not chat_prompt:
                await message.reply('**Error**\nGunakan format: `!chat [pertanyaan atau pesan]`')
                return
            prompt = chat_prompt
        attachment = message.attachments[0] if message.attachments else None
        media_data = None
        if attachment:
            mime_type = attachment.content_type
            if mime_type not in SUPPORTED_MIME_TYPES:
                supported_formats = ', '.join(set(SUPPORTED_MIME_TYPES.keys()))
                await message.reply(
                    f'**Error**\nFormat file tidak didukung.\n**Format yang didukung:** {supported_formats}')
                return
            async with message.channel.typing():
                file_data = await download_attachment(attachment)
                if file_data is None:
                    await message.reply(
                        '**Error**\nGagal mengunduh file atau file terlalu besar (maksimal 25MB)!')
                    return
                base64_data = base64.b64encode(file_data).decode('utf-8')
                media_data = {'mime_type': mime_type, 'base64': base64_data}
                try:
                    ai_response = await generate_response(
                        channel_id, prompt, media_data, search_query, False, youtube_url, tenor_url)
                    response_chunks = split_text(ai_response)
                    for i, chunk in enumerate(response_chunks):
                        await message.channel.send(chunk)
                        if i < len(response_chunks) - 1:
                            await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f'Error processing message with attachment: {e}')
                    await message.channel.send(
                        "**Error**\nTerjadi kesalahan saat memproses pesan dengan lampiran.")
        else:
            async with message.channel.typing():
                try:
                    ai_response = await generate_response(
                        channel_id, prompt, None, search_query, False, youtube_url, tenor_url)
                    response_chunks = split_text(ai_response)
                    for i, chunk in enumerate(response_chunks):
                        await message.channel.send(chunk)
                        if i < len(response_chunks) - 1:
                            await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f'Error processing message: {e}')
                    await message.channel.send(
                        "**Error**\nTerjadi kesalahan saat memproses pesan.")
    await bot.process_commands(message)

@bot.event
async def on_disconnect():
    global http_session
    if http_session and not http_session.closed:
        await http_session.close()
    logger.info("Bot disconnected and cleaned up resources")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f'Unhandled error in {event}: {args}, {kwargs}', exc_info=True)

@bot.event
async def on_command_error(ctx, error):
    
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"⏰ Command sedang cooldown. Coba lagi dalam {error.retry_after:.1f} detik.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Argumen yang diperlukan tidak ditemukan. Periksa format command.")
    else:
        logger.error(f'Command error: {error}', exc_info=True)
        await ctx.send("❌ Terjadi kesalahan saat menjalankan command.")

if __name__ == "__main__":
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if http_session and not http_session.closed:
            asyncio.run(http_session.close())