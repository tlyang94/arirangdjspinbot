import os
import json
import threading
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ===== 1. 建立 Web 伺服器供 Render 心跳檢查 =====
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = threading.Thread(target=run_web, daemon=True)
    t.start()

# ===== 2. 初始化與環境變數配置 =====
load_dotenv()
TOKEN = os.getenv('DC_TOKEN') or os.getenv('DISCORD_TOKEN')

def load_song_data():
    try:
        with open('spindata.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 讀取 spindata.json 失敗: {e}")
        return {}

song_data = load_song_data()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def get_display_text(default_val="", zh_val="", kr_val="", en_val="", fallback=""):
    if default_val and str(default_val).strip():
        return default_val
    if zh_val and str(zh_val).strip():
        return zh_val
    if kr_val and str(kr_val).strip():
        return kr_val
    if en_val and str(en_val).strip():
        return en_val
    return fallback

# 排序輔助工具：優先取 release_yrmn，若無則取首次演唱日期，若皆無則排至最後
def get_sort_key(info):
    release = info.get("release_yrmn")
    if release and str(release).strip():
        return str(release).strip()
    
    # 備援：從 history 抓最早的日期
    history = info.get("history", [])
    if history:
        sorted_h = sorted(history, key=lambda x: x.get('date', '9999-99-99'))
        return sorted_h[0].get('date', '9999-99-99')
        
    return '9999-99-99'

@bot.event
async def on_ready():
    print(f'✅ 已成功登入為：{bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"✅ 已成功同步 {len(synced)} 個斜線指令！")
    except Exception as e:
        print(f"❌ 同步斜線指令失敗: {e}")


# ==================== 指令 1：/song (搜尋單曲) ====================
@bot.tree.command(name="song", description="查詢歌曲演唱紀錄")
@app_commands.describe(song_name="輸入歌曲名稱關鍵字")
async def check_song(interaction: discord.Interaction, song_name: str):
    await interaction.response.defer(ephemeral=True)
    matched_key = None
    query = song_name.lower().strip()
    
    for key, info in song_data.items():
        title_def = info.get("title", "").lower()
        title_zh = info.get("title_zh", "").lower()
        title_en = info.get("title_en", "").lower()
        title_kr = info.get("title_kr", "").lower()
        
        if query in key.lower() or (title_def and query in title_def) or \
           (title_zh and query in title_zh) or (title_en and query in title_en) or (title_kr and query in title_kr):
            matched_key = key
            break
            
    if not matched_key:
        await interaction.followup.send(f"❌ 找不到歌曲 `{song_name}` 的演唱紀錄。", ephemeral=True)
        return

    info = song_data[matched_key]
    song_title = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), matched_key)
    album_name = get_display_text(info.get('album_zh'), info.get('album_kr'), info.get('album_en'), info.get('album'), "未知專輯")
    release_yrmn = info.get("release_yrmn", "")
    album_display = f"`{album_name}` ({release_yrmn})" if release_yrmn else f"`{album_name}`"

    embed = discord.Embed(
        title=f"🌸 ARIRANG SPIN Tracker: {song_title}",
        color=discord.Color.purple()
    )
    # 將 inline 皆設為 False，演唱次數就會固定排在專輯的下一行
    embed.add_field(name="收錄專輯", value=album_display, inline=False)
    embed.add_field(name="演唱次數", value=f"**{info.get('count', 0)} 次**", inline=False)
    
    # 歷史場次按日期舊到新排序
    history_list = sorted(info.get('history', []), key=lambda x: x.get('date', ''))
    
    history_text = ""
    for h in history_list:
        city_display = get_display_text(h.get('city_zh'), h.get('city_kr'), h.get('city_en'), h.get('city'), "未知城市")
        note_display = f" — *{h.get('note')}*" if h.get('note') else ""
        history_text += f"• `{h.get('date')}` | {city_display}{note_display}\n"
        
    embed.add_field(name="演唱場次", value=history_text if history_text else "尚無場次紀錄", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==================== 指令 2：/album (搜尋專輯) ====================
@bot.tree.command(name="album", description="查詢特定專輯曲目的演唱城市與次數")
@app_commands.describe(album_name="輸入專輯名稱 (關鍵字皆可)")
async def check_album(interaction: discord.Interaction, album_name: str):
    await interaction.response.defer(ephemeral=True)
    query = album_name.lower().strip()
    matched_songs = []
    matched_album_display = ""
    matched_release_yrmn = ""

    for song_title, info in song_data.items():
        album_def = info.get("album", "")
        album_zh = info.get("album_zh", "")
        album_en = info.get("album_en", "")
        album_kr = info.get("album_kr", "")
        
        if (album_def and query in album_def.lower()) or \
           (album_zh and query in album_zh.lower()) or \
           (album_en and query in album_en.lower()) or \
           (album_kr and query in album_kr.lower()):
            
            if not matched_album_display:
                matched_album_display = get_display_text(album_zh, album_kr, album_en, album_def, album_name)
                matched_release_yrmn = info.get("release_yrmn", "")
                
            song_display = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), song_title)
            history = sorted(info.get("history", []), key=lambda x: x.get('date', ''))
            
            # 使用發行年月排序；若無發行年月則使用首次演唱日期
            sort_key = get_sort_key(info)
            matched_songs.append((song_display, info.get("count", 0), history, sort_key))

    if not matched_songs:
        await interaction.followup.send(f"❌ 找不到與 `{album_name}` 相關的專輯歌曲資料。", ephemeral=True)
        return

# 專輯內的曲目依發行年月/日期排序
    matched_songs = sorted(matched_songs, key=lambda x: x[3])

    # 計算該專輯共演唱幾首歌曲
    total_performed_songs = len(matched_songs)

    album_title_text = f"💿 專輯《{matched_album_display}》"
    if matched_release_yrmn:
        album_title_text += f" ({matched_release_yrmn})"
    album_title_text += " 演唱統計"

    embed = discord.Embed(
        title=album_title_text,
        color=discord.Color.blue()
    )

    # 關鍵修改：讓 song_list_text 一開始就帶有「共演唱 X 首」
    song_list_text = f"🎶 **該專輯共演唱了 {total_performed_songs} 首**\n\n"

    for title, count, history, _ in matched_songs:
        song_list_text += f"• **{title}** - `{count} 次`\n"
        
        if history:
            for h in history:
                city_display = get_display_text(h.get('city_zh'), h.get('city_kr'), h.get('city_en'), h.get('city'), "未知城市")
                note_display = f" — *{h.get('note')}*" if h.get('note') else ""
                song_list_text += f"  └ `{h.get('date')}` {city_display}{note_display}\n"
        else:
            song_list_text += "  └ *(無演唱場次紀錄)*\n"
        
        song_list_text += "\n"

    if len(song_list_text) > 4000:
        song_list_text = song_list_text[:3950] + "\n\n*(內容過長，已截斷部分場次...)*"

    embed.description = song_list_text
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==================== 指令 3：/city (搜尋城市) ====================
@bot.tree.command(name="city", description="查詢特定城市演唱歌曲 (按日期群組顯示)")
@app_commands.describe(city_name="輸入城市名稱")
async def check_city(interaction: discord.Interaction, city_name: str):
    await interaction.response.defer(ephemeral=True)
    query = city_name.lower().strip()
    
    # 用字典依日期整理歌曲： { "2024-05-10": [(song, album, note), ...], ... }
    date_grouped_records = {}
    matched_city_display = ""
    total_song_count = 0

    for song_title, info in song_data.items():
        song_display = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), song_title)
        album_display = get_display_text(info.get('album_zh'), info.get('album_kr'), info.get('album_en'), info.get('album'), "未知專輯")
        
        # 取得發行年月
        release_yrmn = info.get("release_yrmn", "")
        album_with_release = f"{album_display} ({release_yrmn})" if release_yrmn else album_display
        
        for h in info.get("history", []):
            city_def = h.get("city", "")
            city_zh = h.get("city_zh", "")
            city_en = h.get("city_en", "")
            city_kr = h.get("city_kr", "")
            
            if (city_def and query in city_def.lower()) or \
               (city_zh and query in city_zh.lower()) or \
               (city_en and query in city_en.lower()) or \
               (city_kr and query in city_kr.lower()):
                
                if not matched_city_display:
                    matched_city_display = get_display_text(city_zh, city_kr, city_en, city_def, city_name)
                    
                event_date = h.get('date', '未知日期')
                note = h.get('note', '')
                
                if event_date not in date_grouped_records:
                    date_grouped_records[event_date] = []
                
                date_grouped_records[event_date].append((song_display, album_with_release, note))
                total_song_count += 1

    if not date_grouped_records:
        await interaction.followup.send(f"❌ 找不到在城市 `{city_name}` 的演唱紀錄。", ephemeral=True)
        return

    # 依日期由舊到新排序
    sorted_dates = sorted(date_grouped_records.keys())
    total_shows = len(sorted_dates)

    embed = discord.Embed(
        title=f"🏙️ 城市－{matched_city_display} 共 {total_shows} 場 / {total_song_count} 首",
        color=discord.Color.green()
    )

    city_list_text = ""
    for date in sorted_dates:
        city_list_text += f"📅 `{date}`\n"
        songs = date_grouped_records[date]
        for song_display, album_with_release, note in songs:
            note_display = f" — *{note}*" if note else ""
            city_list_text += f"  └ **{song_display}** `[{album_with_release}]`{note_display}\n"
        city_list_text += "\n"

    if len(city_list_text) > 4000:
        city_list_text = city_list_text[:3950] + "\n\n*(內容過長，已截斷部分紀錄...)*"

    embed.description = city_list_text
    await interaction.followup.send(embed=embed, ephemeral=True)

# ==================== 指令 4：/count (依演唱次數查詢歌曲清單) ====================
@bot.tree.command(name="count", description="查詢指定演唱次數的所有歌曲與場次細節")
@app_commands.describe(times="輸入要查詢的演唱次數 (例如: 1, 3, 5)")
async def check_count(interaction: discord.Interaction, times: int):
    await interaction.response.defer(ephemeral=True)
    
    if times < 0:
        await interaction.followup.send("❌ 演唱次數不能為負數喔！", ephemeral=True)
        return

    matched_songs = []

    for key, info in song_data.items():
        song_count = info.get("count", 0)
        if song_count == times:
            song_title = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), key)
            album_name = get_display_text(info.get('album_zh'), info.get('album_kr'), info.get('album_en'), info.get('album'), "未知專輯")
            
            history = sorted(info.get("history", []), key=lambda x: x.get('date', ''))
            # 取 release_yrmn 排序
            sort_key = get_sort_key(info)
            matched_songs.append((song_title, album_name, history, sort_key))

    if not matched_songs:
        await interaction.followup.send(f"❌ 找不到演唱次數為 `{times}` 次的歌曲。", ephemeral=True)
        return

    # 清單依歌曲發行年月排序
    matched_songs = sorted(matched_songs, key=lambda x: x[3])

    embed = discord.Embed(
        title=f"📊 演唱次數為 {times} 次的歌曲共 {len(matched_songs)} 首",
        color=discord.Color.gold()
    )

    result_text = ""
    for song_title, album_name, history, _ in matched_songs:
        result_text += f"🎵 **{song_title}** `[{album_name}]`\n"
        if history:
            for h in history:
                city_display = get_display_text(h.get('city_zh'), h.get('city_kr'), h.get('city_en'), h.get('city'), "未知城市")
                note_display = f" — *{h.get('note')}*" if h.get('note') else ""
                result_text += f"  └ `{h.get('date')}` | {city_display}{note_display}\n"
        else:
            result_text += "  └ *(無詳細場次紀錄)*\n"
        result_text += "\n"

    if len(result_text) > 4000:
        result_text = result_text[:3950] + "\n\n*(內容過長，已截斷部分歌曲...)*"

    embed.description = result_text
    await interaction.followup.send(embed=embed, ephemeral=True)


# ===== 3. 主程式進入點 =====
if __name__ == "__main__":
    # 1. 啟動 Web 伺服器給 Render Health Check
    keep_alive()
    
    # 2. 啟動 Discord Bot
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ 錯誤：未偵測到 DC_TOKEN 或 DISCORD_TOKEN，請檢查環境變數設定。")
