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
    # 必須顯式回傳 200 狀態碼，確保 Render 健康檢查成功
    return "Bot is alive!", 200

def run_web():
    # 讀取 Render 自動分配的 PORT，若無則預設 8080
    port = int(os.environ.get("PORT", 8080))
    # 關閉 debug 模式與自動重載，避免執行緒重複建立
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    # 在背景執行緒啟動 Web 伺服器
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# ===== 2. 初始化與環境變數配置 =====
load_dotenv()
# 優先讀取 DC_TOKEN，若不存在則嘗試讀取 DISCORD_TOKEN
TOKEN = os.getenv('DC_TOKEN') or os.getenv('DISCORD_TOKEN')

# 讀取歌曲 JSON 資料庫
def load_song_data():
    try:
        with open('spindata.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 讀取 spindata.json 失敗: {e}")
        return {}

song_data = load_song_data()

# 初始化 Discord Bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# 統一工具函式：優先順序 default > 中文 > 韓文 > 英文 > fallback
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

# Bot 啟動事件：自動同步斜線指令
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
    await interaction.response.defer()
    matched_key = None
    query = song_name.lower().strip()
    
    # 支援 JSON Key、default 及中/英/韓搜尋
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
    
    # 決定歌名與專輯顯示
    song_title = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), matched_key)
    album_name = get_display_text(info.get('album_zh'), info.get('album_kr'), info.get('album_en'), info.get('album'), "未知專輯")

    embed = discord.Embed(
        title=f"🌸 ARIRANG SPIN Tracker: {song_title}",
        color=discord.Color.purple()
    )
    embed.add_field(name="收錄專輯", value=f"`{album_name}`", inline=True)
    embed.add_field(name="演唱次數", value=f"**{info.get('count', 0)} 次**", inline=True)
    
    history_text = ""
    for h in info.get('history', []):
        city_display = get_display_text(h.get('city_zh'), h.get('city_kr'), h.get('city_en'), h.get('city'), "未知城市")
        note_display = f" — *{h.get('note')}*" if h.get('note') else ""
        history_text += f"• `{h.get('date')}` | {city_display}{note_display}\n"
        
    embed.add_field(name="演唱場次", value=history_text if history_text else "尚無場次紀錄", inline=False)
    await interaction.followup.send(embed=embed)


# ==================== 指令 2：/album (搜尋專輯) ====================
@bot.tree.command(name="album", description="查詢特定專輯曲目的演唱城市與次數")
@app_commands.describe(album_name="輸入專輯名稱 (關鍵字皆可)")
async def check_album(interaction: discord.Interaction, album_name: str):
    await interaction.response.defer()
    query = album_name.lower().strip()
    matched_songs = []
    matched_album_display = ""

    for song_title, info in song_data.items():
        album_def = info.get("album", "")
        album_zh = info.get("album_zh", "")
        album_en = info.get("album_en", "")
        album_kr = info.get("album_kr", "")
        
        # 匹配 default 與中英韓欄位
        if (album_def and query in album_def.lower()) or \
           (album_zh and query in album_zh.lower()) or \
           (album_en and query in album_en.lower()) or \
           (album_kr and query in album_kr.lower()):
            
            if not matched_album_display:
                matched_album_display = get_display_text(album_zh, album_kr, album_en, album_def, album_name)
                
            song_display = get_display_text(info.get('title_zh'), info.get('title_kr'), info.get('title_en'), info.get('title'), song_title)
            history = info.get("history", [])
            matched_songs.append((song_display, info.get("count", 0), history))

    if not matched_songs:
        await interaction.followup.send(f"❌ 找不到與 `{album_name}` 相關的專輯歌曲資料。", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"💿 專輯《{matched_album_display}》演唱統計",
        color=discord.Color.blue()
    )

    song_list_text = ""
    for title, count, history in matched_songs:
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
    await interaction.followup.send(embed=embed)


# ==================== 指令 3：/city (搜尋城市，含專輯名稱) ====================
@bot.tree.command(name="city", description="查詢特定城市演唱歌曲")
@app_commands.describe(city_name="輸入城市名稱")
async def check_city(interaction: discord.Interaction, city_name: str):
    await interaction.response.defer()
    query = city_name.lower().strip()
    matched_results = []
    matched_city_display = ""

    for song_title, info in song_data.items():
        song_display = get_display_text(info.get('title'), info.get('title_zh'), info.get('title_kr'), info.get('title_en'), song_title)
        album_display = get_display_text(info.get('album'), info.get('album_zh'), info.get('album_kr'), info.get('album_en'), "未知專輯")
        
        city_records = []
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
                    matched_city_display = get_display_text(city_def, city_zh, city_kr, city_en, city_name)
                    
                city_records.append(h)
                
        if city_records:
            matched_results.append((song_display, album_display, city_records))

    if not matched_results:
        await interaction.followup.send(f"❌ 找不到在城市 `{city_name}` 的演唱紀錄。", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🏙️ 城市－{matched_city_display} 演唱曲目",
        color=discord.Color.green()
    )

    city_list_text = ""
    for song_display, album_display, records in matched_results:
        city_list_text += f"• **{song_display}** `[{album_display}]`\n"
        for r in records:
            note_display = f" — *{r.get('note')}*" if r.get('note') else ""
            city_list_text += f"  └ `{r.get('date')}`{note_display}\n"
        city_list_text += "\n"

    if len(city_list_text) > 4000:
        city_list_text = city_list_text[:3950] + "\n\n*(內容過長，已截斷部分紀錄...)*"

    embed.description = city_list_text
    await interaction.followup.send(embed=embed)


# ===== 3. 主程式進入點 =====
if __name__ == "__main__":
    # 1. 啟動 Web 伺服器給 Render Health Check
    keep_alive()
    
    # 2. 啟動 Discord Bot
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ 錯誤：未偵測到 DC_TOKEN 或 DISCORD_TOKEN，請檢查環境變數設定。")
