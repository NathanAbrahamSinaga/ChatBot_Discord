import os
import base64
import asyncio
import io
import time
import logging
from dotenv import load_dotenv
from discord import Client, Intents, Interaction, app_commands, Attachment, ButtonStyle, ui, Embed, Color, File, FFmpegPCMAudio
from discord.ext import commands
import google.genai as genai
import google.genai.types as types
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch
from bs4 import BeautifulSoup
import aiohttp
from typing import Optional, Dict, List, Tuple
import re
import json
from datetime import datetime, timezone
import lxml
from collections import Counter, defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

required_env_vars = ['GEMINI_API_KEY', 'DISCORD_TOKEN', 'GOOGLE_API_KEY', 'GOOGLE_CSE_ID', 'VOICEVOX_API_KEY']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
    exit(1)

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
VOICEVOX_API_KEY = os.getenv('VOICEVOX_API_KEY')

system_prompt = """
Jawab dengan bahasa Indonesia. Pastikan output rapi dan mudah dibaca di Discord menggunakan format Markdown:
- Gunakan # untuk heading besar, ## untuk subheading.
- Gunakan - untuk bullet point pada list.
- Gunakan ** untuk teks tebal, * untuk italic.
- Gunakan ``` untuk blok kode (contoh: ```python).
- Pisahkan paragraf dengan baris kosong.
- Batasi pesan agar tidak melebihi 2000 karakter.
- Jika ada tautan GIF dari Tenor, jangan analisis kontennya, tetapi respon seperti manusia biasa dengan nada ramah dan santai, misalnya "Haha, GIF-nya lucu banget, makasih ya!" atau sesuai konteks.
- Jika ada URL yang diberikan, gunakan sebagai konteks untuk menjawab pertanyaan.
"""

trend_analysis_prompt = """
Analisis percakapan berikut dan berikan kesimpulan dalam format yang rapi untuk Discord:

1. **Topik Utama yang Dibahas** - list 5-10 topik paling sering muncul
2. **Jenis Pertanyaan Favorit** - kategori pertanyaan yang paling sering ditanya
3. **Pola Interaksi** - waktu paling aktif, panjang percakapan rata-rata
4. **Minat dan Preferensi** - tema yang paling menarik bagi user
5. **Saran** - rekomendasi topik untuk eksplorasi lebih lanjut

Gunakan emoji dan format markdown yang menarik. Maksimal 1500 karakter.
"""

VOICEVOX_SPEAKERS_DATA = [{"name":"四国めたん","speaker_uuid":"7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff","styles":[{"name":"ノーマル","id":2,"type":"talk"},{"name":"あまあま","id":0,"type":"talk"},{"name":"ツンツン","id":6,"type":"talk"},{"name":"セクシー","id":4,"type":"talk"},{"name":"ささやき","id":36,"type":"talk"},{"name":"ヒソヒソ","id":37,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"ずんだもん","speaker_uuid":"388f246b-8c41-4ac1-8e2d-5d79f3ff56d9","styles":[{"name":"ノーマル","id":3,"type":"talk"},{"name":"あまあま","id":1,"type":"talk"},{"name":"ツンツン","id":7,"type":"talk"},{"name":"セクシー","id":5,"type":"talk"},{"name":"ささやき","id":22,"type":"talk"},{"name":"ヒソヒソ","id":38,"type":"talk"},{"name":"ヘロヘロ","id":75,"type":"talk"},{"name":"なみだめ","id":76,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"春日部つむぎ","speaker_uuid":"35b2c544-660e-401e-b503-0e14c635303a","styles":[{"name":"ノーマル","id":8,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"雨晴はう","speaker_uuid":"3474ee95-c274-47f9-aa1a-8322163d96f1","styles":[{"name":"ノーマル","id":10,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"波音リツ","speaker_uuid":"b1a81618-b27b-40d2-b0ea-27a9ad408c4b","styles":[{"name":"ノーマル","id":9,"type":"talk"},{"name":"クイーン","id":65,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"玄野武宏","speaker_uuid":"c30dc15a-0992-4f8d-8bb8-ad3b314e6a6f","styles":[{"name":"ノーマル","id":11,"type":"talk"},{"name":"喜び","id":39,"type":"talk"},{"name":"ツンギレ","id":40,"type":"talk"},{"name":"悲しみ","id":41,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"白上虎太郎","speaker_uuid":"e5020595-5c5d-4e87-b849-270a518d0dcf","styles":[{"name":"ふつう","id":12,"type":"talk"},{"name":"わーい","id":32,"type":"talk"},{"name":"びくびく","id":33,"type":"talk"},{"name":"おこ","id":34,"type":"talk"},{"name":"びえーん","id":35,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"青山龍星","speaker_uuid":"4f51116a-d9ee-4516-925d-21f183e2afad","styles":[{"name":"ノーマル","id":13,"type":"talk"},{"name":"熱血","id":81,"type":"talk"},{"name":"不機嫌","id":82,"type":"talk"},{"name":"喜び","id":83,"type":"talk"},{"name":"しっとり","id":84,"type":"talk"},{"name":"かなしみ","id":85,"type":"talk"},{"name":"囁き","id":86,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"冥鳴ひまり","speaker_uuid":"8eaad775-3119-417e-8cf4-2a10bfd592c8","styles":[{"name":"ノーマル","id":14,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"九州そら","speaker_uuid":"481fb609-6446-4870-9f46-90c4dd623403","styles":[{"name":"ノーマル","id":16,"type":"talk"},{"name":"あまあま","id":15,"type":"talk"},{"name":"ツンツン","id":18,"type":"talk"},{"name":"セクシー","id":17,"type":"talk"},{"name":"ささやき","id":19,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"もち子さん","speaker_uuid":"9f3ee141-26ad-437e-97bd-d22298d02ad2","styles":[{"name":"ノーマル","id":20,"type":"talk"},{"name":"セクシー／あん子","id":66,"type":"talk"},{"name":"泣き","id":77,"type":"talk"},{"name":"怒り","id":78,"type":"talk"},{"name":"喜び","id":79,"type":"talk"},{"name":"のんびり","id":80,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"剣崎雌雄","speaker_uuid":"1a17ca16-7ee5-4ea5-b191-2f02ace24d21","styles":[{"name":"ノーマル","id":21,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"WhiteCUL","speaker_uuid":"67d5d8da-acd7-4207-bb10-b5542d3a663b","styles":[{"name":"ノーマル","id":23,"type":"talk"},{"name":"たのしい","id":24,"type":"talk"},{"name":"かなしい","id":25,"type":"talk"},{"name":"びえーん","id":26,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"後鬼","speaker_uuid":"0f56c2f2-644c-49c9-8989-94e11f7129d0","styles":[{"name":"人間ver.","id":27,"type":"talk"},{"name":"ぬいぐるみver.","id":28,"type":"talk"},{"name":"人間（怒り）ver.","id":87,"type":"talk"},{"name":"鬼ver.","id":88,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"No.7","speaker_uuid":"044830d2-f23b-44d6-ac0d-b5d733caa900","styles":[{"name":"ノーマル","id":29,"type":"talk"},{"name":"アナウンス","id":30,"type":"talk"},{"name":"読み聞かせ","id":31,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"ちび式じい","speaker_uuid":"468b8e94-9da4-4f7a-8715-a22a48844f9e","styles":[{"name":"ノーマル","id":42,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"櫻歌ミコ","speaker_uuid":"0693554c-338e-4790-8982-b9c6d476dc69","styles":[{"name":"ノーマル","id":43,"type":"talk"},{"name":"第二形態","id":44,"type":"talk"},{"name":"ロリ","id":45,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"小夜/SAYO","speaker_uuid":"a8cc6d22-aad0-4ab8-bf1e-2f843924164a","styles":[{"name":"ノーマル","id":46,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"ナースロボ＿タイプＴ","speaker_uuid":"882a636f-3bac-431a-966d-c5e6bba9f949","styles":[{"name":"ノーマル","id":47,"type":"talk"},{"name":"楽々","id":48,"type":"talk"},{"name":"恐怖","id":49,"type":"talk"},{"name":"内緒話","id":50,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"†聖騎士 紅桜†","speaker_uuid":"471e39d2-fb11-4c8c-8d89-4b322d2498e0","styles":[{"name":"ノーマル","id":51,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"雀松朱司","speaker_uuid":"0acebdee-a4a5-4e12-a695-e19609728e30","styles":[{"name":"ノーマル","id":52,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"麒ヶ島宗麟","speaker_uuid":"7d1e7ba7-f957-40e5-a3fc-da49f769ab65","styles":[{"name":"ノーマル","id":53,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"春歌ナナ","speaker_uuid":"ba5d2428-f7e0-4c20-ac41-9dd56e9178b4","styles":[{"name":"ノーマル","id":54,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"猫使アル","speaker_uuid":"00a5c10c-d3bd-459f-83fd-43180b521a44","styles":[{"name":"ノーマル","id":55,"type":"talk"},{"name":"おちつき","id":56,"type":"talk"},{"name":"うきうき","id":57,"type":"talk"},{"name":"つよつよ","id":110,"type":"talk"},{"name":"へろへろ","id":111,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"猫使ビィ","speaker_uuid":"c20a2254-0349-4470-9fc8-e5c0f8cf3404","styles":[{"name":"ノーマル","id":58,"type":"talk"},{"name":"おちつき","id":59,"type":"talk"},{"name":"人見知り","id":60,"type":"talk"},{"name":"つよつよ","id":112,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"中国うさぎ","speaker_uuid":"1f18ffc3-47ea-4ce0-9829-0576d03a7ec8","styles":[{"name":"ノーマル","id":61,"type":"talk"},{"name":"おどろき","id":62,"type":"talk"},{"name":"こわがり","id":63,"type":"talk"},{"name":"へろへろ","id":64,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"栗田まろん","speaker_uuid":"04dbd989-32d0-40b4-9e71-17c920f2a8a9","styles":[{"name":"ノーマル","id":67,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"あいえるたん","speaker_uuid":"dda44ade-5f9c-4a3a-9d2c-2a976c7476d9","styles":[{"name":"ノーマル","id":68,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"満別花丸","speaker_uuid":"287aa49f-e56b-4530-a469-855776c84a8d","styles":[{"name":"ノーマル","id":69,"type":"talk"},{"name":"元気","id":70,"type":"talk"},{"name":"ささやき","id":71,"type":"talk"},{"name":"ぶりっ子","id":72,"type":"talk"},{"name":"ボーイ","id":73,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"琴詠ニア","speaker_uuid":"97a4af4b-086e-4efd-b125-7ae2da85e697","styles":[{"name":"ノーマル","id":74,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"Voidoll","speaker_uuid":"0ebe2c7d-96f3-4f0e-a2e3-ae13fe27c403","styles":[{"name":"ノーマル","id":89,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"NOTHING"}},{"name":"ぞん子","speaker_uuid":"0156da66-4300-474a-a398-49eb2e8dd853","styles":[{"name":"ノーマル","id":90,"type":"talk"},{"name":"低血圧","id":91,"type":"talk"},{"name":"覚醒","id":92,"type":"talk"},{"name":"実況風","id":93,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"中部つるぎ","speaker_uuid":"4614a7de-9829-465d-9791-97eb8a5f9b86","styles":[{"name":"ノーマル","id":94,"type":"talk"},{"name":"怒り","id":95,"type":"talk"},{"name":"ヒソヒソ","id":96,"type":"talk"},{"name":"おどおど","id":97,"type":"talk"},{"name":"絶望と敗北","id":98,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"離途","speaker_uuid":"3b91e034-e028-4acb-a08d-fbdcd207ea63","styles":[{"name":"ノーマル","id":99,"type":"talk"},{"name":"シリアス","id":101,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"黒沢冴白","speaker_uuid":"0b466290-f9b6-4718-8d37-6c0c81e824ac","styles":[{"name":"ノーマル","id":100,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"ユーレイちゃん","speaker_uuid":"462cd6b4-c088-42b0-b357-3816e24f112e","styles":[{"name":"ノーマル","id":102,"type":"talk"},{"name":"甘々","id":103,"type":"talk"},{"name":"哀しみ","id":104,"type":"talk"},{"name":"ささやき","id":105,"type":"talk"},{"name":"ツクモちゃん","id":106,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"ALL"}},{"name":"東北ずん子","speaker_uuid":"80802b2d-8c75-4429-978b-515105017010","styles":[{"name":"ノーマル","id":107,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"東北きりたん","speaker_uuid":"1bd6b32b-d650-4072-bbe5-1d0ef4aaa28b","styles":[{"name":"ノーマル","id":108,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}},{"name":"東北イタコ","speaker_uuid":"ab4c31a3-8769-422a-b412-708f5ae637e8","styles":[{"name":"ノーマル","id":109,"type":"talk"}],"version":"0.15.9","supported_features":{"permitted_synthesis_morphing":"SELF_ONLY"}}]
VOICEVOX_ROMAJI_MAP = { "四国めたん": "Shikoku Metan", "ずんだもん": "Zundamon", "春日部つむぎ": "Kasukabe Tsumugi", "雨晴はう": "Amehare Hau", "波音リツ": "Namine Ritsu", "玄野武宏": "Kurono Takehiro", "白上虎太郎": "Shirakami Kotarou", "青山龍星": "Aoyama Ryuusei", "冥鳴ひまり": "Meimei Himari", "九州そら": "Kyuushuu Sora", "もち子さん": "Mochiko-san", "剣崎雌雄": "Kenzaki Mesuo", "WhiteCUL": "WhiteCUL", "後鬼": "Goki", "No.7": "No.7", "ちび式じい": "Chibishiki-jii", "櫻歌ミコ": "Ouka Miko", "小夜/SAYO": "Sayo", "ナースロボ＿タイプＴ": "Nurse-robo Type T", "†聖騎士 紅桜†": "Seikishi Benizakura", "雀松朱司": "Jakumatsu Shushi", "麒ヶ島宗麟": "Kigashima Sourin", "春歌ナナ": "Haruka Nana", "猫使アル": "Nekotsukai Al", "猫使ビィ": "Nekotsukai B", "中国うさぎ": "Chuugoku Usagi", "栗田まろん": "Kurita Maron", "あいえるたん": "Aieru-tan", "満別花丸": "Manbetsu Hanamaru", "琴詠ニア": "Kotoe Nia", "Voidoll": "Voidoll", "ぞん子": "Zonko", "中部つるぎ": "Chubu Tsurugi", "離途": "Rito", "黒沢冴白": "Kurosawa Saehiro", "ユーレイちゃん": "Yuurei-chan", "東北ずん子": "Tohoku Zunko", "東北きりたん": "Tohoku Kiritan", "東北イタコ": "Tohoku Itako" }

PROCESSED_SPEAKERS = []
for speaker in VOICEVOX_SPEAKERS_DATA:
    jp_name = speaker["name"]
    romaji_name = VOICEVOX_ROMAJI_MAP.get(jp_name, "")
    display_name = f"{jp_name} ({romaji_name})" if romaji_name else jp_name
    processed_styles = []
    for style in speaker["styles"]:
        style_name_map = { "ノーマル": "Normal", "あまあま": "Sweet", "ツンツン": "Tsuntsun", "セクシー": "Sexy", "ささやき": "Whisper", "ヒソヒソ": "Hushed", "ヘロヘロ": "Dizzy", "なみだめ": "Teary-eyed", "クイーン": "Queen", "喜び": "Joy", "ツンギレ": "Tsun-gire", "悲しみ": "Sorrow", "ふつう": "Normal", "わーい": "Yay", "びくびく": "Scared", "おこ": "Angry", "びえーん": "Crying", "熱血": "Passionate", "不機嫌": "Grumpy", "しっとり": "Gentle", "かなしみ": "Sadness", "囁き": "Whisper", "セクシー／あん子": "Sexy/Anko", "泣き": "Crying", "怒り": "Anger", "のんびり": "Relaxed", "たのしい": "Fun", "かなしい": "Sad", "人間ver.": "Human ver.", "ぬいぐるみver.": "Plushie ver.", "人間（怒り）ver.": "Human (Angry) ver.", "鬼ver.": "Oni ver.", "アナウンス": "Announce", "読み聞かせ": "Read-aloud", "第二形態": "Second Form", "ロリ": "Loli", "楽々": "Cheerful", "恐怖": "Fear", "内緒話": "Secret talk", "おちつき": "Calm", "うきうき": "Excited", "つよつよ": "Forceful", "人見知り": "Shy", "おどろき": "Surprised", "こわがり": "Scaredy-cat", "元気": "Energetic", "ぶりっ子": "Cutesy", "ボーイ": "Boyish", "低血圧": "Low-energy", "覚醒": "Awakened", "実況風": "Play-by-play", "おどおど": "Nervous", "絶望と敗北": "Despair and Defeat", "シリアス": "Serious", "甘々": "Sweet", "哀しみ": "Sorrow", "ツクモちゃん": "Tsukumo-chan" }
        en_name = style_name_map.get(style["name"], style["name"])
        processed_styles.append({ "id": style["id"], "display_name": f'{style["name"]} ({en_name})' })
    PROCESSED_SPEAKERS.append({ "uuid": speaker["speaker_uuid"], "display_name": display_name, "styles": processed_styles })

class ConversationTracker:
    def __init__(self):
        self.messages = defaultdict(list)
        self.topics = defaultdict(Counter)
        self.timestamps = defaultdict(list)
        self.question_types = defaultdict(Counter)
        self.user_interests = defaultdict(Counter)
    def add_message(self, channel_id: str, user_id: str, content: str, timestamp: float):
        message_data = { 'user_id': user_id, 'content': content, 'timestamp': timestamp, 'datetime': datetime.fromtimestamp(timestamp) }
        self.messages[channel_id].append(message_data)
        self.timestamps[channel_id].append(timestamp)
        self._extract_topics(channel_id, content)
        self._classify_question_type(channel_id, content)
        self._extract_interests(channel_id, user_id, content)
    def _extract_topics(self, channel_id: str, content: str):
        content_lower = content.lower()
        tech_keywords = ['python', 'javascript', 'coding', 'programming', 'ai', 'machine learning', 'discord', 'bot', 'api']
        science_keywords = ['fisika', 'kimia', 'biologi', 'matematika', 'sains', 'research', 'study']
        general_keywords = ['cara', 'bagaimana', 'mengapa', 'apa itu', 'tutorial', 'belajar', 'help']
        entertainment_keywords = ['game', 'musik', 'film', 'anime', 'entertainment', 'fun', 'meme']
        business_keywords = ['bisnis', 'marketing', 'startup', 'investasi', 'uang', 'karir']
        for keyword in tech_keywords:
            if keyword in content_lower: self.topics[channel_id]['Teknologi'] += 1
        for keyword in science_keywords:
            if keyword in content_lower: self.topics[channel_id]['Sains & Pendidikan'] += 1
        for keyword in general_keywords:
            if keyword in content_lower: self.topics[channel_id]['Bantuan Umum'] += 1
        for keyword in entertainment_keywords:
            if keyword in content_lower: self.topics[channel_id]['Hiburan'] += 1
        for keyword in business_keywords:
            if keyword in content_lower: self.topics[channel_id]['Bisnis & Karir'] += 1
    def _classify_question_type(self, channel_id: str, content: str):
        content_lower = content.lower()
        if any(word in content_lower for word in ['cara', 'bagaimana', 'how to']): self.question_types[channel_id]['Tutorial/Panduan'] += 1
        elif any(word in content_lower for word in ['apa', 'what', 'definisi']): self.question_types[channel_id]['Definisi/Penjelasan'] += 1
        elif any(word in content_lower for word in ['mengapa', 'kenapa', 'why']): self.question_types[channel_id]['Analisis/Alasan'] += 1
        elif any(word in content_lower for word in ['help', 'tolong', 'bantuan', 'error']): self.question_types[channel_id]['Bantuan/Troubleshooting'] += 1
        elif any(word in content_lower for word in ['rekomendasikan', 'saran', 'recommend']): self.question_types[channel_id]['Rekomendasi'] += 1
    def _extract_interests(self, channel_id: str, user_id: str, content: str):
        words = content.lower().split()
        for word in words:
            if len(word) > 3: self.user_interests[f"{channel_id}_{user_id}"][word] += 1
    def get_trend_analysis(self, channel_id: str) -> str:
        if channel_id not in self.messages or not self.messages[channel_id]: return "📊 **Analisis Trend**\n\nBelum ada data percakapan untuk dianalisis."
        messages = self.messages[channel_id]
        total_messages = len(messages)
        top_topics = self.topics[channel_id].most_common(5)
        top_question_types = self.question_types[channel_id].most_common(3)
        recent_messages = [msg for msg in messages if time.time() - msg['timestamp'] < 86400]
        active_hours = Counter([msg['datetime'].hour for msg in messages])
        most_active_hour = active_hours.most_common(1)[0] if active_hours else (12, 0)
        analysis = f"📊 **Analisis Trend Percakapan**\n\n"
        analysis += f"💬 **Total Pesan:** {total_messages}\n"
        analysis += f"📅 **Pesan Hari Ini:** {len(recent_messages)}\n"
        analysis += f"⏰ **Jam Teraktif:** {most_active_hour[0]:02d}:00\n\n"
        if top_topics:
            analysis += f"🔥 **Topik Terpopuler:**\n"
            for i, (topic, count) in enumerate(top_topics, 1):
                percentage = (count / total_messages) * 100
                analysis += f"{i}. {topic}: {count} pesan ({percentage:.1f}%)\n"
            analysis += "\n"
        if top_question_types:
            analysis += f"❓ **Jenis Pertanyaan Favorit:**\n"
            for i, (q_type, count) in enumerate(top_question_types, 1):
                analysis += f"{i}. {q_type}: {count}x\n"
            analysis += "\n"
        avg_msg_length = sum(len(msg['content']) for msg in messages) / total_messages if messages else 0
        analysis += f"📝 **Rata-rata Panjang Pesan:** {avg_msg_length:.0f} karakter\n\n"
        suggestions = []
        if not any('Teknologi' in topic for topic, _ in top_topics): suggestions.append("💻 Eksplorasi topik teknologi dan programming")
        if not any('Sains' in topic for topic, _ in top_topics): suggestions.append("🔬 Pelajari sains dan pengetahuan umum")
        if avg_msg_length < 50: suggestions.append("📚 Coba pertanyaan yang lebih detail untuk jawaban mendalam")
        if suggestions:
            analysis += f"💡 **Saran Eksplorasi:**\n"
            for suggestion in suggestions[:3]: analysis += f"- {suggestion}\n"
        return analysis

class BotState:
    def __init__(self):
        self.conversation_history: Dict[str, any] = {}
        self.command_cooldowns: Dict[str, float] = {}
        self.channel_activity: Dict[str, bool] = {}
        self.last_activity: Dict[str, float] = {}
        self.last_button_message: Dict[str, any] = {}
        self.tracker = ConversationTracker()
    def cleanup_old_data(self):
        current_time = time.time()
        expired_cooldowns = [ key for key, timestamp in self.command_cooldowns.items() if current_time > timestamp ]
        for key in expired_cooldowns: del self.command_cooldowns[key]

bot_state = BotState()
COOLDOWN_TIME = 30
MAX_FILE_SIZE = 25 * 1024 * 1024
INACTIVITY_TIMEOUT = 600
SUPPORTED_MIME_TYPES = { 'image/jpeg': 'image', 'image/png': 'image', 'image/gif': 'image', 'application/pdf': 'pdf', 'video/mp4': 'video', 'video/mpeg': 'video', 'audio/mp3': 'audio', 'audio/mpeg': 'audio', 'audio/wav': 'audio', 'image/jpg': 'image' }
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
            if response.status != 200: return f"**Error Scraping**\nHTTP {response.status}: Gagal mengambil konten dari {url}."
            html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        content = ""
        for elem in soup.select('p, h1, h2, h3, article, main'):
            text = elem.get_text().strip()
            if text: content += text + '\n'
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
            if response.status != 200: return f"**Error**\nGoogle Search API error: {response.status}"
            data = await response.json()
        if not data.get('items'): return "**Hasil Pencarian**\nMaaf, tidak ada hasil yang ditemukan untuk pencarian ini."
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

def extract_urls(text: str) -> List[str]:
    url_pattern = r'(https?://[^\s]+)'
    urls = re.findall(url_pattern, text)
    return [url for url in urls if not (re.search(r'tenor\.com', url) or re.search(r'youtube\.com|youtu\.be', url))]

def extract_youtube_url(text: str) -> Optional[str]:
    youtube_patterns = [ r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)', r'(https?://youtu\.be/[\w-]+)', r'(https?://(?:www\.)?youtube\.com/embed/[\w-]+)' ]
    for pattern in youtube_patterns:
        match = re.search(pattern, text)
        if match: return match.group(0)
    return None

def extract_tenor_url(text: str) -> Optional[str]:
    tenor_pattern = r'(https?://tenor\.com/view/[\w-]+)'
    match = re.search(tenor_pattern, text)
    return match.group(0) if match else None

async def generate_response(channel_id: str, prompt: str, media_data: Optional[Dict] = None, search_query: Optional[str] = None, use_thinking: bool = False, youtube_url: Optional[str] = None, tenor_url: Optional[str] = None, urls: Optional[List[str]] = None) -> str:
    try:
        model_name = "gemini-2.5-flash" if use_thinking else "gemini-2.5-pro"
        if channel_id not in bot_state.conversation_history:
            url_context_tool = Tool(url_context=types.UrlContext())
            tools = [url_context_tool]
            if search_query: tools.append(Tool(google_search=types.GoogleSearch()))
            bot_state.conversation_history[channel_id] = client.chats.create( model=model_name, config=types.GenerateContentConfig( system_instruction=system_prompt, temperature=0.9, max_output_tokens=4000, tools=tools))
        chat = bot_state.conversation_history[channel_id]
        contents = [prompt]
        if search_query:
            search_results = await google_search(search_query)
            contents.append(search_results)
        if media_data:
            if media_data['mime_type'] == 'application/pdf':
                pdf_buffer = base64.b64decode(media_data['base64'])
                if len(pdf_buffer) > MAX_FILE_SIZE: return "**Error**\nFile PDF terlalu besar. Maksimal 25MB."
                pdf_file = client.files.upload( file=io.BytesIO(pdf_buffer), config=dict(mime_type='application/pdf'))
                contents.append(pdf_file)
            else:
                file_data = base64.b64decode(media_data['base64'])
                if len(file_data) > MAX_FILE_SIZE: return "**Error**\nFile terlalu besar. Maksimal 25MB."
                contents.append( types.Part.from_bytes( data=file_data, mime_type=media_data['mime_type']))
        if youtube_url: contents.append( types.Part(file_data=types.FileData(file_uri=youtube_url)))
        if tenor_url: contents.append(tenor_url)
        if urls:
            for url in urls:
                web_content = await fetch_web_content(url)
                contents.append(f"Konten dari {url}:\n{web_content}")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: chat.send_message(contents))
        response_text = response.text
        if hasattr(response.candidates[0], 'url_context_metadata'):
            url_metadata = response.candidates[0].url_context_metadata
            if url_metadata and url_metadata.url_metadata:
                response_text += "\n\n**Sumber URL yang Digunakan:**\n"
                for meta in url_metadata.url_metadata:
                    status = meta.url_retrieval_status
                    status_text = "Berhasil" if status == types.UrlRetrievalStatus.URL_RETRIEVAL_STATUS_SUCCESS else "Gagal"
                    response_text += f"- {meta.retrieved_url}: {status_text}\n"
        if not any(marker in response_text for marker in ['#', '-', '```']):
            paragraphs = [p.strip() for p in response_text.split('\n\n') if p.strip()]
            response_text = '\n\n' + '\n\n'.join(paragraphs)
        return response_text
    except asyncio.TimeoutError: return "**Error**\nTimeout: Permintaan memakan waktu terlalu lama."
    except Exception as error:
        logger.error(f'Error di generateResponse: {error}')
        return f"**Error**\nTerjadi kesalahan saat menghasilkan respons: {str(error)}"

async def generate_trend_analysis(channel_id: str) -> str:
    try:
        if channel_id not in bot_state.conversation_history: return "📊 **Analisis Trend**\n\nBelum ada riwayat percakapan untuk dianalisis."
        messages_data = []
        for message_data in bot_state.tracker.messages[channel_id]: messages_data.append(f"User: {message_data['content']}")
        if len(messages_data) < 5: return bot_state.tracker.get_trend_analysis(channel_id)
        conversation_text = "\n".join(messages_data[-50:])
        chat = client.chats.create( model="gemini-1.5-flash-latest", config=types.GenerateContentConfig( system_instruction=trend_analysis_prompt, temperature=0.7, max_output_tokens=2000))
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: chat.send_message([conversation_text]))
        basic_analysis = bot_state.tracker.get_trend_analysis(channel_id)
        ai_analysis = response.text
        return f"{basic_analysis}\n\n🤖 **Analisis AI:**\n{ai_analysis}"
    except Exception as error:
        logger.error(f'Error generating trend analysis: {error}')
        return bot_state.tracker.get_trend_analysis(channel_id)

async def generate_trend_analysis_embed(channel_id: str) -> Embed:
    analysis_text = await generate_trend_analysis(channel_id)
    embed = Embed( title="📊 Analisis Trend Percakapan", description=analysis_text, color=Color.blue(), timestamp=datetime.now() )
    embed.set_footer(text="Analisis diperbarui otomatis")
    return embed

def split_text(text: str, max_length: int = 1900) -> List[str]:
    if len(text) <= max_length: return [text]
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
            else: in_code_block = False
            if len(current_chunk) + len(line_with_newline) > max_length:
                if in_code_block: current_chunk += '\n```'
                chunks.append(current_chunk.strip())
                current_chunk = line_with_newline
            else: current_chunk += line_with_newline
            continue
        if len(line) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ''
            for i in range(0, len(line), max_length): chunks.append(line[i:i + max_length])
        else:
            if len(current_chunk) + len(line_with_newline) > max_length:
                if in_code_block: current_chunk += '\n```'
                chunks.append(current_chunk.strip())
                current_chunk = f"```{current_language}\n" if in_code_block else ""
                current_chunk += line_with_newline
            else: current_chunk += line_with_newline
    if current_chunk.strip():
        if in_code_block and not current_chunk.endswith('```'): current_chunk += '\n```'
        chunks.append(current_chunk.strip())
    return [chunk for chunk in chunks if chunk.strip()]

def check_cooldown(user_id: str, command: str) -> Tuple[bool, float]:
    cooldown_key = f"{user_id}-{command}"
    current_time = time.time()
    cooldown_end_time = bot_state.command_cooldowns.get(cooldown_key, 0)
    if current_time < cooldown_end_time:
        remaining_time = cooldown_end_time - current_time
        return True, remaining_time
    normal_cooldown = 30
    bot_state.command_cooldowns[cooldown_key] = current_time + normal_cooldown
    return False, 0

class InteractionButtons(ui.View):
    def __init__(self, channel_id: str):
        super().__init__(timeout=None)
        self.channel_id = channel_id
    @ui.button(label="New", style=ButtonStyle.green, custom_id="new_conversation")
    async def new_button(self, interaction: Interaction, button: ui.Button):
        channel_id = str(interaction.channel_id)
        if channel_id in bot_state.conversation_history: bot_state.conversation_history.pop(channel_id)
        bot_state.channel_activity[channel_id] = True
        bot_state.last_activity[channel_id] = time.time()
        if channel_id in bot_state.last_button_message:
            try:
                await bot_state.last_button_message[channel_id].delete()
                del bot_state.last_button_message[channel_id]
            except Exception as e: logger.error(f"Error deleting button message: {e}")
        embed = Embed( description="✅ Percakapan baru telah dimulai! Kirim pesan untuk melanjutkan.", color=Color.green())
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
            except Exception as e: logger.error(f"Error deleting button message: {e}")
        embed = Embed( description="✅ Melanjutkan percakapan! Kirim pesan untuk melanjutkan.", color=Color.blurple())
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
    except Exception as e: logger.error(f"Failed to sync commands: {e}")

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
                            embed = Embed( title="Bot Tidak Aktif", description="Bot telah tidak aktif selama 10 menit. Pilih opsi di bawah untuk melanjutkan:", color=Color.blue())
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
    if on_cooldown: await interaction.response.send_message( f"**Cooldown**\nSilakan tunggu {remaining_time:.1f} detik sebelum menggunakan perintah ini lagi.", ephemeral=True); return
    bot_state.channel_activity[channel_id] = True
    bot_state.last_activity[channel_id] = time.time()
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e: logger.error(f"Error deleting button message: {e}")
    await interaction.response.send_message("**Status**\nBot diaktifkan di channel ini!")

@bot.tree.command(name="deactivate", description="Menonaktifkan bot di channel ini")
async def deactivate(interaction: Interaction):
    user_id = str(interaction.user.id)
    channel_id = str(interaction.channel_id)
    on_cooldown, remaining_time = check_cooldown(user_id, "deactivate")
    if on_cooldown: await interaction.response.send_message( f"**Cooldown**\nSilakan tunggu {remaining_time:.1f} detik sebelum menggunakan perintah ini lagi.", ephemeral=True); return
    bot_state.channel_activity[channel_id] = False
    if channel_id in bot_state.last_activity: del bot_state.last_activity[channel_id]
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e: logger.error(f"Error deleting button message: {e}")
    await interaction.response.send_message("**Status**\nBot dinonaktifkan di channel ini!")

async def download_attachment(attachment: Attachment) -> Optional[bytes]:
    try:
        if attachment.size > MAX_FILE_SIZE: return None
        session = await get_http_session()
        async with session.get(attachment.url) as response:
            if response.status == 200: return await response.read()
        return None
    except Exception as e:
        logger.error(f'Error downloading attachment: {e}')
        return None

class SpeakerTransformer(app_commands.Transformer):
    async def transform(self, interaction: Interaction, value: str) -> str: return value
    async def autocomplete(self, interaction: Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = [ app_commands.Choice(name=speaker['display_name'], value=speaker['uuid']) for speaker in PROCESSED_SPEAKERS if current.lower() in speaker['display_name'].lower() ]
        return choices[:25]

class StyleTransformer(app_commands.Transformer):
    async def transform(self, interaction: Interaction, value: str) -> int: return int(value)
    async def autocomplete(self, interaction: Interaction, current: str) -> List[app_commands.Choice[int]]:
        speaker_uuid = interaction.namespace.karakter
        if not speaker_uuid: return [app_commands.Choice(name="Pilih karakter dulu...", value=-1)]
        choices = []
        for speaker in PROCESSED_SPEAKERS:
            if speaker['uuid'] == speaker_uuid:
                for style in speaker['styles']:
                    if current.lower() in style['display_name'].lower(): choices.append(app_commands.Choice(name=style['display_name'], value=style['id']))
                break
        return choices[:25]

@bot.tree.command(name="suara", description="Mengirim pesan suara menggunakan VoiceVox.")
@app_commands.describe( text="Teks yang akan diucapkan.", karakter="Pilih karakter suara.", gaya="Pilih gaya atau emosi suara." )
async def suara( interaction: Interaction, text: str, karakter: app_commands.Transform[str, SpeakerTransformer], gaya: app_commands.Transform[int, StyleTransformer] ):
    if not interaction.user.voice: await interaction.response.send_message("❌ Kamu harus berada di voice channel untuk menggunakan perintah ini.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected(): await voice_client.move_to(voice_channel)
    else:
        try: voice_client = await voice_channel.connect()
        except Exception as e:
            logger.error(f"Error connecting to voice channel: {e}")
            await interaction.followup.send("Gagal terhubung ke voice channel.", ephemeral=True)
            return
    try:
        session = await get_http_session()
        api_url = f"https://voicevox.su-shiki.com/su-shikiapis/tts?text={text}&speaker={gaya}&key={VOICEVOX_API_KEY}"
        async with session.get(api_url) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"VoiceVox API Error {response.status}: {error_text}")
                await interaction.followup.send(f"⚠️ Gagal menghasilkan suara. Error: {response.status}", ephemeral=True)
                if voice_client.is_connected(): await voice_client.disconnect()
                return
            audio_data = await response.read()
            audio_source = FFmpegPCMAudio(io.BytesIO(audio_data), pipe=True)
            await interaction.followup.send("🔊 Memainkan suara...", ephemeral=True)
            voice_client.play(audio_source, after=lambda e: logger.info(f'Finished playing: {e}'))
            while voice_client.is_playing(): await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error in /suara command: {e}")
        await interaction.followup.send("❌ Terjadi kesalahan saat memproses permintaan suara.", ephemeral=True)
    finally:
        if voice_client and not voice_client.is_playing() and voice_client.is_connected():
            await asyncio.sleep(1)
            await voice_client.disconnect()

@bot.event
async def on_message(message):
    if message.author.bot: return
    channel_id = str(message.channel.id)
    is_bot_active = bot_state.channel_activity.get(channel_id, False)
    content = message.content.strip()
    user_id = str(message.author.id)
    current_time = time.time()
    bot_state.tracker.add_message(channel_id, user_id, content, current_time)
    user_last_message = bot_state.command_cooldowns.get(f"{user_id}-message", 0)
    if current_time - user_last_message < 2: return
    bot_state.command_cooldowns[f"{user_id}-message"] = current_time
    bot_state.last_activity[channel_id] = current_time
    if channel_id in bot_state.last_button_message:
        try:
            await bot_state.last_button_message[channel_id].delete()
            del bot_state.last_button_message[channel_id]
        except Exception as e: logger.error(f"Error deleting event {e}")
    if content.lower() == '!reset':
        if channel_id in bot_state.conversation_history:
            bot_state.conversation_history.pop(channel_id)
            await message.channel.send('✅ Riwayat percakapan di channel ini telah direset!')
        else: await message.channel.send('ℹ️ Tidak ada riwayat percakapan yang perlu dihapus')
        return
    if content.lower() == '!kesimpulan':
        async with message.channel.typing():
            try:
                embed = await generate_trend_analysis_embed(channel_id)
                await message.channel.send(embed=embed)
            except Exception as e:
                logger.error(f'Error generating trend analysis: {e}')
                await message.channel.send("**Error**\nTerjadi kesalahan saat menghasilkan analisis trend.")
        return
    if content.lower().startswith('!think'):
        async with message.channel.typing():
            thinking_prompt = content.replace('!think', '', 1).strip()
            if not thinking_prompt: await message.reply('**Error**\nGunakan format: `!think [pertanyaan atau permintaan]`'); return
            attachment = message.attachments[0] if message.attachments else None
            media_data = None
            urls = extract_urls(thinking_prompt)
            if attachment:
                mime_type = attachment.content_type
                if mime_type not in SUPPORTED_MIME_TYPES:
                    supported_formats = ', '.join(set(SUPPORTED_MIME_TYPES.keys()))
                    await message.reply(f'**Error**\nFormat file tidak didukung.\n**Format yang didukung:** {supported_formats}'); return
                file_data = await download_attachment(attachment)
                if file_data is None: await message.reply('**Error**\nGagal mengunduh file atau file terlalu besar (maksimal 25MB)!'); return
                base64_data = base64.b64encode(file_data).decode('utf-8')
                media_data = {'mime_type': mime_type, 'base64': base64_data}
            try:
                ai_response = await generate_response(channel_id, thinking_prompt, media_data, None, True, None, None, urls)
                response_chunks = split_text(ai_response)
                for i, chunk in enumerate(response_chunks):
                    await message.channel.send(chunk)
                    if i < len(response_chunks) - 1: await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f'Error in think command: {e}')
                await message.channel.send("**Error**\nTerjadi kesalahan saat memproses permintaan thinking.")
        return
    if is_bot_active or content.startswith('!chat'):
        prompt = content
        search_query = None
        youtube_url = extract_youtube_url(content)
        tenor_url = extract_tenor_url(content)
        urls = extract_urls(content)
        if content.startswith('!chat'):
            chat_prompt = content.replace('!chat', '', 1).strip()
            if not chat_prompt: await message.reply('**Error**\nGunakan format: `!chat [pertanyaan atau pesan]`'); return
            prompt = chat_prompt
        attachment = message.attachments[0] if message.attachments else None
        media_data = None
        if attachment:
            mime_type = attachment.content_type
            if mime_type not in SUPPORTED_MIME_TYPES:
                supported_formats = ', '.join(set(SUPPORTED_MIME_TYPES.keys()))
                await message.reply(f'**Error**\nFormat file tidak didukung.\n**Format yang didukung:** {supported_formats}'); return
            async with message.channel.typing():
                file_data = await download_attachment(attachment)
                if file_data is None: await message.reply('**Error**\nGagal mengunduh file atau file terlalu besar (maksimal 25MB)!'); return
                base64_data = base64.b64encode(file_data).decode('utf-8')
                media_data = {'mime_type': mime_type, 'base64': base64_data}
                try:
                    ai_response = await generate_response( channel_id, prompt, media_data, search_query, False, youtube_url, tenor_url, urls)
                    bot_state.tracker.add_message(channel_id, "bot", ai_response, current_time)
                    response_chunks = split_text(ai_response)
                    for i, chunk in enumerate(response_chunks):
                        await message.channel.send(chunk)
                        if i < len(response_chunks) - 1: await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f'Error processing message with attachment: {e}')
                    await message.channel.send("**Error**\nTerjadi kesalahan saat memproses pesan dengan lampiran.")
        else:
            async with message.channel.typing():
                try:
                    ai_response = await generate_response( channel_id, prompt, None, search_query, False, youtube_url, tenor_url, urls)
                    bot_state.tracker.add_message(channel_id, "bot", ai_response, current_time)
                    response_chunks = split_text(ai_response)
                    for i, chunk in enumerate(response_chunks):
                        await message.channel.send(chunk)
                        if i < len(response_chunks) - 1: await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f'Error processing message: {e}')
                    await message.channel.send("**Error**\nTerjadi kesalahan saat memproses pesan.")
    await bot.process_commands(message)

@bot.event
async def on_disconnect():
    global http_session
    if http_session and not http_session.closed: await http_session.close()
    logger.info("Bot disconnected and cleaned up resources")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f'Unhandled error in {event}: {args}, {kwargs}', exc_info=True)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown): await ctx.send(f"⏰ Command sedang cooldown. Coba lagi dalam {error.retry_after:.1f} detik.")
    elif isinstance(error, commands.MissingRequiredArgument): await ctx.send("❌ Argumen yang diperlukan tidak ditemukan. Periksa format command.")
    else:
        logger.error(f'Command error: {error}', exc_info=True)
        await ctx.send("❌ Terjadi kesalahan saat menjalankan command.")

if __name__ == "__main__":
    try: bot.run(os.getenv('DISCORD_TOKEN'))
    except KeyboardInterrupt: logger.info("Bot stopped by user")
    except Exception as e: logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if http_session and not http_session.closed: asyncio.run(http_session.close())