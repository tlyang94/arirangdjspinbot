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
    embed.add_field(name="演唱次數", value=f"{info.get('count', 0)} 次", inline=False)
    
    # 歷史場次按日期舊到新排序
    history_list = sorted(info.get('history', []), key=lambda x: x.get('date', ''))
    
    history_text = ""
    for h in history_list:
        city_display = get_display_text(h.get('city_zh'), h.get('city_kr'), h.get('city_en'), h.get('city'), "未知城市")
        note_display = f" — *{h.get('note')}*" if h.get('note') else ""
        history_text += f"• `{h.get('date')}` | {city_display}{note_display}\n"
        
    embed.add_field(name="演唱場次", value=history_text if history_text else "尚無場次紀錄", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==================== 指令 2：/album (搜尋專輯或系列專輯名稱) ====================
@bot.tree.command(name="album", description="搜尋專輯名稱或專輯系列 (例如: 花樣年華, Love Yourself)")
@app_commands.describe(album_name="輸入專輯名稱或系列關鍵字")
async def check_album(interaction: discord.Interaction, album_name: str):
    await interaction.response.defer(ephemeral=True)
    query = album_name.lower().strip()
    
    # 紀錄匹配到的專輯與對應的歌曲資料
    matched_albums = set()
    album_songs_map = {} # { "專輯名稱(發行年月)": [ (song_display, history_list), ... ] }
    total_song_count = 0

    for song_title, info in song_data.items():
        song_display = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), song_title)
        
        album_zh = info.get('album_zh', '')
        album_kr = info.get('album_kr', '')
        album_en = info.get('album_en', '')
        album_def = info.get('album', '')
        release_yrmn = info.get('release_yrmn', '')
        
        # 檢查關鍵字是否出現在任何語言的專輯名稱中 (支援前綴與系列模糊比對)
        if (album_zh and query in album_zh.lower()) or \
           (album_kr and query in album_kr.lower()) or \
           (album_en and query in album_en.lower()) or \
           (album_def and query in album_def.lower()):
            
            # 取得最佳顯示專輯名
            album_display = get_display_text(album_zh, album_kr, album_en, album_def, "未知專輯")
            album_key = f"{album_display} ({release_yrmn})" if release_yrmn else album_display
            
            matched_albums.add(album_key)
            
            if album_key not in album_songs_map:
                album_songs_map[album_key] = []
            
            album_songs_map[album_key].append((song_display, info.get("history", [])))
            total_song_count += 1

    if not album_songs_map:
        await interaction.followup.send(f"❌ 找不到與專輯/系列 `{album_name}` 相關的紀錄。", ephemeral=True)
        return

    # 建立 Embed 回應
    embed = discord.Embed(
        title=f"💿 搜尋 與{album_name}相關 共 {len(matched_albums)} 張專輯 / {total_song_count} 首已演唱歌曲",
        color=discord.Color.blue()
    )

    album_text = ""
    
    # 按照專輯名稱排序輸出
    for album_key in sorted(album_songs_map.keys()):
        album_text += f"💿 **【{album_key}】**\n"
        songs = album_songs_map[album_key]
        
        for song_display, history in songs:
            album_text += f"  └ **{song_display}**\n"
            
            if history:
                # 演唱紀錄按日期排序
                sorted_history = sorted(history, key=lambda x: x.get('date', ''))
                for h in sorted_history:
                    date = h.get('date', '未知日期')
                    city_def = h.get('city', '')
                    city_zh = h.get('city_zh', '')
                    clean_city = city_zh.split("|")[-1] if "|" in city_zh else city_zh
                    city_display = f"{clean_city} ({city_def})" if clean_city and city_def else (clean_city or city_def or "未知城市")
                    note = f" — *{h.get('note')}*" if h.get('note') else ""
                    
                    album_text += f"`{date}` @ {city_display}{note}\n"
            else:
                album_text += f"      *(尚無巡演首次演唱紀錄)*\n"
        
        album_text += "\n"

    # 防止訊息超越 Discord Embed 4000 字限制
    if len(album_text) > 4000:
        album_text = album_text[:3950] + "\n\n*(內容過長，已截斷部分紀錄...)*"

    embed.description = album_text
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==================== 指令 3：/city (搜尋國家/地區/城市，城市與日期皆依時間由舊到新排序) ====================
@bot.tree.command(name="city", description="詢特定國家或區域（美國——州）或城市演唱歌曲")
@app_commands.describe(city_name="輸入國家、州名或城市名稱 (例如: 南韓, 馬德里, Stanford)")
async def check_city(interaction: discord.Interaction, city_name: str):
    await interaction.response.defer(ephemeral=True)
    query = city_name.lower().strip()
    
    # 建立暫存結構，將「曲目為主」的資料反向歸類為「城市 -> 日期 -> 歌曲」
    city_grouped_records = {}
    total_song_count = 0
    all_dates = set()

    # 1. 遍歷每首歌曲與其 history 紀錄
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
            
            # 檢查搜尋關鍵字是否匹配國家、州名或城市
            if (city_def and query in city_def.lower()) or \
               (city_zh and query in city_zh.lower()) or \
               (city_en and query in city_en.lower()) or \
               (city_kr and query in city_kr.lower()):
                
                # 擷取精簡城市名稱 (如 "美國|德州|艾爾帕索" -> "艾爾帕索")
                if "|" in city_zh:
                    clean_city_zh = city_zh.split("|")[-1]
                else:
                    clean_city_zh = city_zh
                
                # 組合城市標頭名稱
                city_key = clean_city_zh if clean_city_zh else (city_def or "未知城市")

                event_date = h.get('date', '9999-99-99')
                note = h.get('note', '')
                
                if city_key not in city_grouped_records:
                    city_grouped_records[city_key] = {}
                
                if event_date not in city_grouped_records[city_key]:
                    city_grouped_records[city_key][event_date] = []
                
                # 將歌曲放入對應的城市與日期中
                city_grouped_records[city_key][event_date].append((song_display, album_with_release, note))
                total_song_count += 1
                all_dates.add(event_date)

    if not city_grouped_records:
        await interaction.followup.send(f"❌ 找不到與 `{city_name}` 相關的演唱紀錄。", ephemeral=True)
        return

    # 2. 計算總場次 (去除同日期多首歌重複計算)
    total_shows = len(all_dates)

    # 3. 關鍵排序：依據各城市「第一場演唱會的日期」來排序城市的顯示順序 (由舊到新)
    def get_min_date_for_city(city_item):
        dates = city_item[1].keys()
        return min(dates) if dates else "9999-99-99"

    sorted_cities = sorted(city_grouped_records.items(), key=get_min_date_for_city)

    embed = discord.Embed(
        title=f"🏙️ 搜尋 與{city_name}相符 共{total_shows}場 / {total_song_count}首已演唱歌曲",
        color=discord.Color.green()
    )

    result_text = ""
    
    # 4. 組成輸出格式
    for city_display_name, dates_dict in sorted_cities:
        result_text += f"📍 **{city_display_name}**\n"
        
        # 城市內部的日期依時間由舊到新排序
        sorted_dates = sorted(dates_dict.keys())
        
        for date in sorted_dates:
            result_text += f"`{date}`\n"
            songs = dates_dict[date]
            for song_display, album_with_release, note in songs:
                note_display = f" — *{note}*" if note else ""
                result_text += f"  └ **{song_display}** `[{album_with_release}]`{note_display}\n"
        
        result_text += "\n"

    # 防止訊息超越 Discord Embed 4000 字限制
    if len(result_text) > 4000:
        result_text = result_text[:3950] + "\n\n*(內容過長，已截斷部分紀錄...)*"

    embed.description = result_text
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
        title=f"📊 演唱{times}次的歌曲 共 {len(matched_songs)} 首",
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
