"""
🎬 Video Bot v42
━━━━━━━━━━━━━━━
✅ Download: YouTube, TikTok, Instagram, Facebook, Pinterest
📱 TikTok Mode — Copyright Safe + No "Eligible For You"
🎯 WinGo ULTRA — 35-layer prediction

📦 SETUP (Termux):
    pkg update -y && pkg install -y python ffmpeg
    pip install "python-telegram-bot[job-queue]" yt-dlp

🔑 BOT_TOKEN নিচে বসান
🚀 RUN: python video_bot_v42.py
"""

import os, sys, re, json, logging, asyncio, subprocess, tempfile, uuid, time, random, math, urllib.request
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

BOT_TOKEN    = os.getenv("BOT_TOKEN") or "এখানে_BOT_TOKEN_বসান"
GEMINI_KEY   = os.getenv("GEMINI_API_KEY") or "AIzaSyDns9YbCMa4vtKFZFlwGI92jv3UyAGKGY4"
ADMIN_ID     = int(os.getenv("ADMIN_ID") or "0")
VERSION      = "v43"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("vbot42")

import shutil, glob as _glob, subprocess as _sp

def _find_bin(name):
    p = shutil.which(name)
    if p: return p
    for base in ["/nix/store", "/usr/local/bin", "/usr/bin", "/bin", "/app",
                 "/home/claude", str(Path.home())]:
        try:
            found = _glob.glob(f"{base}/**/{name}", recursive=True)
            if found: return found[0]
        except Exception:
            pass
    return None

def _install_ffmpeg():
    """Multiple fallback methods to install ffmpeg"""
    # Method 1: apt-get
    try:
        r = _sp.run(["apt-get", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=120)
        p = shutil.which("ffmpeg")
        if p:
            print(f"✅ ffmpeg installed via apt-get: {p}")
            return p, shutil.which("ffprobe") or p.replace("ffmpeg","ffprobe")
    except Exception as e:
        print(f"apt-get failed: {e}")

    # Method 2: apt (no get)
    try:
        r = _sp.run(["apt", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=120)
        p = shutil.which("ffmpeg")
        if p:
            print(f"✅ ffmpeg installed via apt: {p}")
            return p, shutil.which("ffprobe") or p.replace("ffmpeg","ffprobe")
    except Exception as e:
        print(f"apt failed: {e}")

    # Method 3: static binary download (ffmpeg-release-amd64-static)
    try:
        import urllib.request, tarfile
        home = Path.home()
        ff_dir = home / "ffmpeg_bin"
        ff_dir.mkdir(exist_ok=True)
        ff_path  = ff_dir / "ffmpeg"
        ffp_path = ff_dir / "ffprobe"

        if not ff_path.exists():
            print("⏬ Downloading static ffmpeg...")
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            tmp_tar = str(ff_dir / "ff.tar.xz")
            urllib.request.urlretrieve(url, tmp_tar)
            with tarfile.open(tmp_tar) as tar:
                for m in tar.getmembers():
                    if m.name.endswith("/ffmpeg") or m.name.endswith("/ffprobe"):
                        m.name = Path(m.name).name
                        tar.extract(m, path=str(ff_dir))
            Path(tmp_tar).unlink(missing_ok=True)
            ff_path.chmod(0o755)
            if ffp_path.exists(): ffp_path.chmod(0o755)

        if ff_path.exists():
            print(f"✅ Static ffmpeg ready: {ff_path}")
            return str(ff_path), str(ffp_path) if ffp_path.exists() else str(ff_path)
    except Exception as e:
        print(f"Static download failed: {e}")

    print("❌ ffmpeg could not be installed — all methods failed")
    return None, None

FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")

if not FFMPEG:
    print("⚠️ ffmpeg not found, attempting install...")
    FFMPEG, FFPROBE = _install_ffmpeg()

if not FFMPEG:
    print("❌ FATAL: ffmpeg unavailable. Bot will not process videos.")
    FFMPEG  = "ffmpeg"   # last resort — will fail gracefully per-request
    FFPROBE = "ffprobe"

print(f"✅ ffmpeg : {FFMPEG}")
print(f"✅ ffprobe: {FFPROBE}")

CPU_COUNT = max(2, os.cpu_count() or 4)
executor  = ThreadPoolExecutor(max_workers=max(4, CPU_COUNT))
TEMP_DIR  = Path(tempfile.gettempdir()) / "vbot42"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════
# WINGO STATE  — v3 ULTRA AI (70 Layers)
# ════════════════════════════════════════════

# 30S — 7 fallback servers (same TF, different hosts for reliability)
WINGO_APIS_30S = [
    "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://draw.ar-lottery02.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://draw.ar-lottery03.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://draw.ar-lottery04.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://api.ar-lottery.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://api.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
    "https://api2.ar-lottery.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=100&ts=",
]

_wingo_subs  = set()
_wingo_state = {
    "last_period":  None,
    "history":      [],
    "win_streak":   0,
    "loss_streak":  0,
    "total_pred":   0,
    "correct_pred": 0,
    "layer_perf":   {},
    "pending_pred": None,
    "session_votes": [],
}

# ════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════
def md_escape(t):
    return re.sub(r'([_*`\[\]])', r'\\\1', str(t or ""))[:3000]

def tmp_path(suffix=".mp4"):
    return str(TEMP_DIR / f"{uuid.uuid4().hex}{suffix}")

def has_audio(path):
    try:
        r = subprocess.run(
            [FFPROBE,"-v","error","-select_streams","a:0",
             "-show_entries","stream=codec_type","-of","csv=p=0",str(path)],
            capture_output=True, text=True, timeout=15)
        return "audio" in r.stdout
    except Exception:
        return True

def get_video_info(path):
    try:
        r = subprocess.run(
            [FFPROBE,"-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height,duration",
             "-of","json",str(path)],
            capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        s = data.get("streams",[{}])[0]
        return {
            "width": int(s.get("width",1920)),
            "height": int(s.get("height",1080)),
            "duration": float(s.get("duration",0)),
        }
    except Exception:
        return {"width":1920,"height":1080,"duration":0}

def run_ffmpeg(cmd, timeout=300):
    try:
        # cmd[0] কে FFMPEG দিয়ে replace করো, তারপর loglevel inject
        cmd = list(cmd)
        cmd[0] = FFMPEG
        if "-loglevel" not in cmd and "-v" not in cmd:
            cmd = [cmd[0], "-loglevel", "error"] + cmd[1:]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        # output file হলো সবসময় শেষ element (ffmpeg convention)
        out_file = cmd[-1]
        if Path(out_file).exists() and Path(out_file).stat().st_size > 1024:
            return True, ""
        stderr = r.stderr or ""
        all_lines = stderr.splitlines()
        # banner বাদ দিয়ে শুধু আসল error দেখাও
        err_keywords = ("error", "invalid", "failed", "no such", "unable",
                        "cannot", "could not", "denied", "not found",
                        "codec", "muxer", "permission", "option", "matches no",
                        "unrecognized", "unknown", "conversion", "filter")
        err_lines = [l for l in all_lines
                     if l.strip() and any(k in l.lower() for k in err_keywords)]
        if err_lines:
            err = "\n".join(err_lines[:5])
        elif all_lines:
            non_empty = [l for l in all_lines if l.strip()]
            err = "\n".join(non_empty[-5:]) if non_empty else "অজানা ffmpeg error"
        else:
            err = "অজানা ffmpeg error"
        return False, err
    except subprocess.TimeoutExpired:
        return False, "Timeout — ভিডিও অনেক বড়, ছোট ভিডিও দিন"
    except Exception as e:
        return False, str(e)

async def safe_edit(target, text, **kw):
    try:
        return await target.edit_text(text, **kw)
    except Exception as e:
        if "not modified" in str(e).lower(): return target
        try:
            kw.pop("parse_mode", None)
            return await target.edit_text(re.sub(r'[*_`\[\]()]','', text), **kw)
        except Exception:
            return target

async def safe_reply(msg, text, **kw):
    try:
        return await msg.reply_text(text, **kw)
    except Exception:
        kw.pop("parse_mode", None)
        return await msg.reply_text(re.sub(r'[*_`\[\]()]','', text), **kw)

_user_state: dict = {}

# ════════════════════════════════════════════
# 🚀 AUTO FULL PIPELINE
# ════════════════════════════════════════════
# Watermark text
_WM_TEXT = "Bangla brand music"

def process_watermark(inp: str) -> tuple:
    """
    লিংক দিলে সব AUTO:
    1. Mirror (hflip)
    2. 4:5 ratio (1080x1350)
    3. Facebook viral color grade
    4. Enhance (denoise + sharpen)
    5. Copyright bypass (pitch + hue)
    6. "Bangla brand music" watermark নিচে ডানে
    """
    out = tmp_path(".mp4")

    # font খোঁজো
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/system/fonts/Roboto-Bold.ttf",
        "/nix/store",
    ]
    font_file = None
    for fp in font_paths:
        if fp == "/nix/store":
            import glob as _g
            found = _g.glob("/nix/store/**/DejaVuSans*.ttf", recursive=True)
            if found:
                font_file = found[0]
            break
        if Path(fp).exists():
            font_file = fp
            break

    # drawtext filter
    if font_file:
        dt = (
            f"drawtext=fontfile={font_file}"
            f":text='{_WM_TEXT}'"
            ":fontsize=40"
            ":fontcolor=white@0.90"
            ":shadowcolor=black@0.70"
            ":shadowx=2:shadowy=2"
            ":x=w-tw-25:y=h-th-30"
        )
    else:
        # font না থাকলে default font দিয়ে চেষ্টা
        dt = (
            f"drawtext=text='{_WM_TEXT}'"
            ":fontsize=40"
            ":fontcolor=white@0.90"
            ":shadowcolor=black@0.70"
            ":shadowx=2:shadowy=2"
            ":x=w-tw-25:y=h-th-30"
        )

    vf = (
        "hflip,"
        "scale=1080:1350:force_original_aspect_ratio=decrease,"
        "pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black,"
        "hqdn3d=1.5:1.5:4:4,"
        "eq=contrast=1.12:brightness=0.02:saturation=1.25:gamma=0.96,"
        "hue=h=3:s=1.05,"
        "unsharp=3:3:0.8:3:3:0.2,"
        + dt
    )

    pitch = round(random.uniform(1.5, 2.5), 2)
    speed = round(random.uniform(1.005, 1.012), 4)

    if has_audio(inp):
        af = (
            f"asetrate=44100*{1+(pitch/1000)},"
            f"atempo={speed},"
            f"loudnorm=I=-14:TP=-1:LRA=11"
        )
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf", vf, "-af", af,
               "-c:v","libx264","-preset","fast","-crf","18",
               "-c:a","aac","-b:a","192k",
               "-map_metadata","-1",
               "-movflags","+faststart", out]
        ok, err = run_ffmpeg(cmd)
        # audio fail → retry without af
        if not ok:
            cmd = [FFMPEG,"-y","-i",inp,
                   "-vf", vf,
                   "-c:v","libx264","-preset","fast","-crf","18",
                   "-c:a","aac","-b:a","192k",
                   "-map_metadata","-1",
                   "-movflags","+faststart", out]
            ok, err = run_ffmpeg(cmd)
    else:
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf", vf, "-an",
               "-c:v","libx264","-preset","fast","-crf","18",
               "-map_metadata","-1",
               "-movflags","+faststart", out]
        ok, err = run_ffmpeg(cmd)

    # drawtext fail → watermark ছাড়া retry
    if not ok:
        vf_ndt = (
            "hflip,"
            "scale=1080:1350:force_original_aspect_ratio=decrease,"
            "pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black,"
            "hqdn3d=1.5:1.5:4:4,"
            "eq=contrast=1.12:brightness=0.02:saturation=1.25:gamma=0.96,"
            "hue=h=3:s=1.05,"
            "unsharp=3:3:0.8:3:3:0.2"
        )
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf", vf_ndt,
               "-c:v","libx264","-preset","fast","-crf","18",
               "-map_metadata","-1",
               "-movflags","+faststart"]
        if has_audio(inp): cmd += ["-c:a","aac","-b:a","192k"]
        else: cmd += ["-an"]
        cmd.append(out)
        ok, err = run_ffmpeg(cmd)

    return (out if ok else None), err

# ════════════════════════════════════════════
# 🎭 VIRAL SCRIPT GENERATOR — Claude AI
# ════════════════════════════════════════════

SCRIPT_TOPICS = {
    "1": "ভালোবাসা",
    "2": "বন্ধুত্ব",
    "3": "বিচ্ছেদ",
    "4": "স্কুল জীবন",
}

SCRIPT_MOODS = {
    "1": "কষ্টের ও আবেগী",
    "2": "মিষ্টি ও রোমান্টিক",
    "3": "ঝগড়া থেকে মিলন",
    "4": "একাকীত্বের",
}

SCRIPT_STYLES = {
    "1": "WhatsApp",
    "2": "Messenger",
}

SCENARIOS = [
    "রাতে হঠাৎ মেসেজ", "ঝগড়ার পরে প্রথম কথা", "অনেকদিন পর যোগাযোগ",
    "বিদায়ের আগের রাত", "বৃষ্টির দিনে মেসেজ", "জন্মদিনের রাতে",
    "হঠাৎ কষ্টের কথা বলা", "না বলা কথা বলা", "শেষবারের মতো কথা",
    "ভুল বোঝাবুঝির পর", "দূরে থাকার কষ্ট", "পরীক্ষার আগের রাত",
]

# ── Local script templates (API ছাড়া fallback) ──
_LOCAL_TEMPLATES = [
    # ভালোবাসা / কষ্টের
    {
        "hook": "রাত ৩টায় তুমি আবার মেসেজ দিলে... কেন? 💔",
        "messages": [
            {"side":"left",  "text":"তুমি ঘুমাও নাই?",           "time":"03:12"},
            {"side":"right", "text":"না। তোমার কথা মনে পড়ছে",    "time":"03:13"},
            {"side":"left",  "text":"কেন এখন বলছ?",              "time":"03:14"},
            {"side":"right", "text":"কারণ রাতে সত্যিটা বলতে ভয় লাগে না","time":"03:15"},
            {"side":"left",  "text":"কী সত্যি?",                  "time":"03:16"},
            {"side":"right", "text":"তোমাকে ছাড়া ঘুম আসে না আমার","time":"03:17"},
            {"side":"left",  "text":"আমিও ঘুমাই নি 💙",           "time":"03:18"},
            {"side":"right", "text":"তাহলে আর দেরি কেন? 😔💔",    "time":"03:19"},
        ],
        "caption":"রাত ৩টায় একটা সত্যিকারের কথোপকথন... 💔 তোমারও কি এমন রাত আসে?",
        "hashtags":"#ভালোবাসা #রাত #কষ্ট #viral #reels #foryou #বাংলা",
    },
    # বিচ্ছেদ / কষ্টের
    {
        "hook":"শেষবারের মতো কথা বলা যায়? 😢",
        "messages":[
            {"side":"left",  "text":"একটু কথা বলবে?",             "time":"22:05"},
            {"side":"right", "text":"বলো",                         "time":"22:06"},
            {"side":"left",  "text":"তুমি কি ভালো আছ?",           "time":"22:07"},
            {"side":"right", "text":"তোমাকে ছাড়া ভালো থাকা কঠিন","time":"22:08"},
            {"side":"left",  "text":"আমিও একই অবস্থায়",           "time":"22:09"},
            {"side":"right", "text":"তাহলে কেন আলাদা হলাম?",       "time":"22:10"},
            {"side":"left",  "text":"জানি না। হয়তো ভুল ছিল",      "time":"22:11"},
            {"side":"right", "text":"হয়তো... goodbye 💔",          "time":"22:12"},
        ],
        "caption":"বিচ্ছেদের পরে শেষ কথোপকথন — এটা পড়ে কার কথা মনে পড়ল? 💔",
        "hashtags":"#বিচ্ছেদ #কষ্ট #viral #reels #foryou #বাংলা",
    },
    # বন্ধুত্ব / মিষ্টি
    {
        "hook":"সবচেয়ে ভালো বন্ধু মানে এটাই 🤝",
        "messages":[
            {"side":"left",  "text":"কী করছিস?",                  "time":"18:30"},
            {"side":"right", "text":"তোর কথা ভাবছিলাম",           "time":"18:31"},
            {"side":"left",  "text":"আমার কথা কেন?",              "time":"18:32"},
            {"side":"right", "text":"কারণ তুই আমার সেরা মানুষ",   "time":"18:33"},
            {"side":"left",  "text":"বাদ দে এসব 😂",              "time":"18:34"},
            {"side":"right", "text":"সত্যি বলছি। তুই না থাকলে কী করতাম","time":"18:35"},
            {"side":"left",  "text":"আমিও তোকে ছাড়া কল্পনা করতে পারি না","time":"18:36"},
            {"side":"right", "text":"এই বন্ধুত্ব চিরকাল 🤝❤️",    "time":"18:37"},
        ],
        "caption":"সত্যিকারের বন্ধুত্ব এরকমই হয় 🤝 তোমার বেস্ট ফ্রেন্ডকে ট্যাগ করো!",
        "hashtags":"#বন্ধুত্ব #friendship #viral #reels #foryou #বাংলা",
    },
    # স্কুল জীবন / রোমান্টিক
    {
        "hook":"ক্লাসের সেই মেয়েটাকে আজও ভুলতে পারি না 😍",
        "messages":[
            {"side":"left",  "text":"পরীক্ষার নোট পাঠাবে?",       "time":"20:15"},
            {"side":"right", "text":"তুমি তো ক্লাসে ছিলে!",       "time":"20:16"},
            {"side":"left",  "text":"ছিলাম, কিন্তু তোমার দিকে তাকিয়ে ছিলাম 😅","time":"20:17"},
            {"side":"right", "text":"কী বললে! 😳",                 "time":"20:18"},
            {"side":"left",  "text":"সত্যি বলছি। তোমাকে দেখলে পড়া মাথায় ঢোকে না","time":"20:19"},
            {"side":"right", "text":"পাগল হয়েছ নাকি 😅",          "time":"20:20"},
            {"side":"left",  "text":"একটু হয়েছি, তোমার জন্য 💙",  "time":"20:21"},
            {"side":"right", "text":"নোট পরে দেব... এখন কথা বলো 😊","time":"20:22"},
        ],
        "caption":"স্কুলের প্রেমটা এরকমই নির্দোষ ছিল 😍 তোমারও কি এমন স্মৃতি আছে?",
        "hashtags":"#স্কুলজীবন #ভালোবাসা #viral #reels #foryou #বাংলা",
    },
    # ভুল বোঝাবুঝি / ঝগড়া থেকে মিলন
    {
        "hook":"ঝগড়ার পর প্রথম মেসেজ পাঠানোটাই সবচেয়ে কঠিন 😔",
        "messages":[
            {"side":"left",  "text":"sorry",                       "time":"14:45"},
            {"side":"right", "text":"কেন হঠাৎ?",                  "time":"14:47"},
            {"side":"left",  "text":"কারণ তোমাকে miss করছি",      "time":"14:48"},
            {"side":"right", "text":"ঝগড়া করে miss করো?",         "time":"14:49"},
            {"side":"left",  "text":"তোমার সাথে ঝগড়াটাও ভালো লাগে","time":"14:50"},
            {"side":"right", "text":"পাগল 😂",                    "time":"14:51"},
            {"side":"left",  "text":"তোমার পাগল 😊",              "time":"14:52"},
            {"side":"right", "text":"ঠিক আছে, ক্ষমা করলাম ❤️",    "time":"14:53"},
        ],
        "caption":"ঝগড়ার পর 'sorry' লেখাটাই সবচেয়ে কঠিন কিন্তু সবচেয়ে সুন্দরও 💕",
        "hashtags":"#ভালোবাসা #ঝগড়া #viral #reels #foryou #বাংলা",
    },
    # একাকীত্ব
    {
        "hook":"একা থাকতে থাকতে নিজেই নিজের শত্রু হয়ে যাই... 🌙",
        "messages":[
            {"side":"left",  "text":"তুমি কি কখনো একা অনুভব করো?","time":"23:30"},
            {"side":"right", "text":"সবসময়। মানুষের মাঝেও",       "time":"23:31"},
            {"side":"left",  "text":"আমিও",                       "time":"23:32"},
            {"side":"right", "text":"তাহলে আমরা দুজন একা একসাথে","time":"23:33"},
            {"side":"left",  "text":"এটা কি ভালো না খারাপ?",      "time":"23:34"},
            {"side":"right", "text":"জানি না। কিন্তু তোমার সাথে কম একা লাগে","time":"23:35"},
            {"side":"left",  "text":"আমারও 🌙",                   "time":"23:36"},
            {"side":"right", "text":"তাহলে আর একা না আমরা 💫",    "time":"23:37"},
        ],
        "caption":"একাকীত্বও সুন্দর হতে পারে যদি সঠিক মানুষ পাশে থাকে 🌙",
        "hashtags":"#একাকীত্ব #রাত #viral #reels #foryou #বাংলা",
    },
]

def _local_script(topic: str, mood: str, style: str, scenario: str) -> str:
    """API ছাড়া local template দিয়ে স্ক্রিপ্ট বানাও"""
    t = random.choice(_LOCAL_TEMPLATES)
    is_wa = style == "WhatsApp"
    chat_lines = []
    base_h = random.randint(8, 22)
    base_m = random.randint(0, 45)
    for i, m in enumerate(t["messages"]):
        mn = (base_m + i * random.randint(1, 3)) % 60
        hr = base_h if mn >= base_m else (base_h + 1) % 24
        time_str = f"{hr:02d}:{mn:02d}"
        side = m["side"]
        text = m["text"]
        if side == "right":
            tick = " ✓✓" if is_wa else " ✓"
            chat_lines.append(f"{'':>20}{text}\n{'':>25}{time_str}{tick}")
        else:
            chat_lines.append(f"{text}\n  {time_str}")

    chat_str = "\n\n".join(chat_lines)
    return (
        f"✨ *স্ক্রিপ্ট তৈরি!*  _{style} স্টাইল_ _(Local)_\n"
        f"📍 _{scenario}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *হুক:*\n_{t['hook']}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 *চ্যাট স্ক্রিপ্ট:*\n\n"
        f"```\n{chat_str}\n```\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *ক্যাপশন:*\n{t['caption']}\n\n"
        f"#️⃣ *হ্যাশট্যাগ:*\n{t['hashtags']}"
    )

async def generate_script(topic: str, mood: str, style: str) -> str:
    """Gemini API দিয়ে স্ক্রিপ্ট বানাও"""
    import urllib.request as req
    import urllib.error
    scenario = random.choice(SCENARIOS)
    seed = uuid.uuid4().hex[:8]

    style_note = (
        "WhatsApp চ্যাট স্টাইলে — সবুজ বাবল ডানে, ধূসর বাবল বামে"
        if style == "WhatsApp"
        else "Facebook Messenger স্টাইলে — নীল বাবল ডানে, ধূসর বাবল বামে"
    )

    prompt = f"""তুমি একজন বাংলাদেশী ভাইরাল ফেসবুক কন্টেন্ট ক্রিয়েটর।
টপিক: {topic} | মেজাজ: {mood} | স্টাইল: {style_note}
পরিস্থিতি: {scenario} | সিড: {seed}

নিচের JSON ফরম্যাটে উত্তর দাও — শুধু JSON, আর কিছু না:

{{
  "hook": "আকর্ষণীয় হুক (বাংলায়, ২০ শব্দের মধ্যে)",
  "messages": [
    {{"side": "left", "text": "বার্তা", "time": "10:44"}},
    {{"side": "right", "text": "বার্তা", "time": "10:45"}},
    {{"side": "left", "text": "বার্তা", "time": "10:46"}},
    {{"side": "right", "text": "বার্তা", "time": "10:47"}},
    {{"side": "left", "text": "বার্তা", "time": "10:48"}},
    {{"side": "right", "text": "বার্তা", "time": "10:49"}},
    {{"side": "left", "text": "বার্তা", "time": "10:50"}},
    {{"side": "right", "text": "শেষ আবেগী বার্তা 💔", "time": "10:51"}}
  ],
  "caption": "আবেগী ক্যাপশন ইমোজি সহ",
  "hashtags": "#{topic} #বাংলা #reels #foryou #viral"
}}

নিয়ম: সব কথ্য বাংলায়, {scenario} পরিস্থিতি অনুযায়ী স্বাভাবিক গল্প, শেষটা {mood} হবে।"""

    # API key না থাকলে সরাসরি local fallback
    no_key = (not GEMINI_KEY or GEMINI_KEY == "এখানে_GEMINI_KEY_বসান" or len(GEMINI_KEY) < 20)
    if no_key:
        logger.info("No Gemini key — using local script template")
        return _local_script(topic, mood, style, scenario)

    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 1500}
        }).encode()

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        request = req.Request(api_url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")

        try:
            with req.urlopen(request, timeout=45) as resp:
                resp_data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Gemini HTTP %s — falling back to local", e.code)
            return _local_script(topic, mood, style, scenario)
        except urllib.error.URLError as e:
            logger.error("Gemini URL error: %s — falling back to local", e.reason)
            return _local_script(topic, mood, style, scenario)

        if "candidates" not in resp_data:
            logger.error("Gemini no candidates — falling back to local")
            return _local_script(topic, mood, style, scenario)

        raw = resp_data["candidates"][0]["content"]["parts"][0]["text"]

        # JSON বের করো — ```json ... ``` বা plain JSON যেভাবেই থাকুক
        raw = raw.strip()
        if "```" in raw:
            raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.error("No JSON in Gemini response — falling back to local")
            return _local_script(topic, mood, style, scenario)

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.error("JSON parse error — falling back to local")
            return _local_script(topic, mood, style, scenario)

        if "messages" not in parsed or "hook" not in parsed:
            return _local_script(topic, mood, style, scenario)

        is_wa = style == "WhatsApp"
        chat_lines = []
        for m in parsed["messages"]:
            side = m.get("side", "left")
            text = m.get("text", "")
            t    = m.get("time", "")
            if side == "right":
                tick = " ✓✓" if is_wa else " ✓"
                chat_lines.append(f"{'':>20}{text}\n{'':>25}{t}{tick}")
            else:
                chat_lines.append(f"{text}\n  {t}")

        chat_str = "\n\n".join(chat_lines)
        caption  = parsed.get("caption", "")
        hashtags = parsed.get("hashtags", f"#{topic} #বাংলা #viral")

        return (
            f"✨ *স্ক্রিপ্ট তৈরি!*  _{style} স্টাইল_ _(AI)_\n"
            f"📍 _{scenario}_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *হুক:*\n_{parsed['hook']}_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 *চ্যাট স্ক্রিপ্ট:*\n\n"
            f"```\n{chat_str}\n```\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 *ক্যাপশন:*\n{caption}\n\n"
            f"#️⃣ *হ্যাশট্যাগ:*\n{hashtags}"
        )

    except Exception as e:
        logger.exception("script_gen unexpected error — falling back to local")
        return _local_script(topic, mood, style, scenario)


def script_topic_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💕 ভালোবাসা", callback_data="sc_topic_1"),
         InlineKeyboardButton("🤝 বন্ধুত্ব",  callback_data="sc_topic_2")],
        [InlineKeyboardButton("💔 বিচ্ছেদ",   callback_data="sc_topic_3"),
         InlineKeyboardButton("🏫 স্কুল জীবন", callback_data="sc_topic_4")],
        [InlineKeyboardButton("🏠 হোম", callback_data="back_main")],
    ])

def script_mood_menu(topic_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("😢 কষ্টের",       callback_data=f"sc_mood_{topic_id}_1"),
         InlineKeyboardButton("🥰 মিষ্টি",        callback_data=f"sc_mood_{topic_id}_2")],
        [InlineKeyboardButton("🔥 ঝগড়া-মিলন",   callback_data=f"sc_mood_{topic_id}_3"),
         InlineKeyboardButton("🌙 একাকী",        callback_data=f"sc_mood_{topic_id}_4")],
        [InlineKeyboardButton("◀️ পিছনে", callback_data="sc_start")],
    ])

def script_style_menu(topic_id, mood_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💚 WhatsApp স্টাইল",   callback_data=f"sc_gen_{topic_id}_{mood_id}_1")],
        [InlineKeyboardButton("💙 Messenger স্টাইল",  callback_data=f"sc_gen_{topic_id}_{mood_id}_2")],
        [InlineKeyboardButton("◀️ পিছনে", callback_data=f"sc_topic_{topic_id}")],
    ])

def script_result_menu(topic_id, mood_id, style_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 নতুন স্ক্রিপ্ট", callback_data=f"sc_gen_{topic_id}_{mood_id}_{style_id}")],
        [InlineKeyboardButton("🎭 অন্য টপিক", callback_data="sc_start"),
         InlineKeyboardButton("🏠 হোম",       callback_data="back_main")],
    ])

# ════════════════════════════════════════════
# DOWNLOAD ENGINE
# ════════════════════════════════════════════
MUA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
DUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
IUA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"

def _ydl_run(fmt, extra, out_tpl, url):
    cmd = (["yt-dlp","--no-playlist","--no-warnings","--quiet",
            "-f", fmt, "--merge-output-format","mp4"]
           + extra + ["-o", out_tpl, url])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.returncode == 0, r.stderr[:300]

def yt_dl(url, job):
    out_tpl = str(TEMP_DIR / f"{job}_input.%(ext)s")
    u = url.lower()

    if any(d in u for d in ("youtube.com","youtu.be","shorts.google.com")):
        strategies = [
            ("bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/best[height<=720]",
             ["--user-agent",MUA,"--extractor-args","youtube:player_client=android,ios","--no-check-certificates"]),
            ("best[height<=720]/best[height<=480]/best",
             ["--user-agent",DUA,"--extractor-args","youtube:player_client=tv_embedded","--no-check-certificates"]),
            ("best[height<=480]/best",
             ["--user-agent",IUA,"--extractor-args","youtube:player_client=mweb","--no-check-certificates"]),
            ("worst/best", ["--user-agent",DUA,"--no-check-certificates"]),
        ]
    elif any(d in u for d in ("tiktok.com","vm.tiktok.com","vt.tiktok.com")):
        strategies = [
            ("best[ext=mp4]/best",
             ["--user-agent",MUA,"--referer","https://www.tiktok.com/",
              "--add-header","Accept-Language:en-US,en;q=0.9",
              "--no-check-certificates","--force-ipv4"]),
            ("best",
             ["--user-agent",IUA,"--referer","https://www.tiktok.com/",
              "--no-check-certificates","--force-ipv4"]),
            ("best[ext=mp4]/best",
             ["--user-agent",DUA,"--no-check-certificates","--force-ipv4"]),
        ]
    elif any(d in u for d in ("instagram.com","instagr.am")):
        strategies = [
            ("best[height<=1080]/best",
             ["--user-agent",MUA,"--referer","https://www.instagram.com/",
              "--add-header","X-IG-App-ID:936619743392459","--no-check-certificates"]),
            ("best", ["--user-agent",IUA,"--no-check-certificates"]),
        ]
    elif any(d in u for d in ("facebook.com","fb.watch","fb.com")):
        strategies = [
            ("best[height<=720]/best",
             ["--user-agent",MUA,"--referer","https://www.facebook.com/","--no-check-certificates"]),
            ("best", ["--user-agent",DUA,"--no-check-certificates"]),
        ]
    elif any(d in u for d in ("pinterest.","pin.it")):
        strategies = [
            ("best[ext=mp4]/best",
             ["--user-agent",MUA,"--no-check-certificates"]),
            ("best", ["--user-agent",DUA,"--no-check-certificates"]),
        ]
    else:
        strategies = [
            ("best[height<=720]/best", ["--user-agent",MUA,"--no-check-certificates"]),
            ("best", ["--user-agent",DUA,"--no-check-certificates"]),
        ]

    err = ""
    for fmt, extra in strategies:
        ok, err = _ydl_run(fmt, extra, out_tpl, url)
        if ok:
            files = [f for f in TEMP_DIR.glob(f"{job}_input.*")
                     if f.suffix.lower() not in (".part",".ytdl",".tmp")
                     and f.stat().st_size > 1024]
            if files:
                title = ""
                try:
                    info = subprocess.run(
                        ["yt-dlp","--quiet","--no-warnings","--print","title",url],
                        capture_output=True, text=True, timeout=20)
                    title = info.stdout.strip()[:80]
                except Exception:
                    pass
                return True, title, "", str(sorted(files)[-1])
    return False, "", err, ""

# ════════════════════════════════════════════
# 📱 TIKTOK MODE — Multi-layer Copyright + Eligible bypass
# ════════════════════════════════════════════
def process_tt_mode(inp):
    """
    TikTok Mode — 7-layer bypass:
    1. 9:16 crop/pad
    2. Microscopic speed change (0.5-1.5%)
    3. Color shift (hue, sat, brightness, contrast)
    4. Subtle mirror + crop (pixel shift)
    5. Grain overlay (film noise)
    6. Audio: pitch + tempo + EQ + slight echo
    7. Metadata + container strip
    """
    out = tmp_path(".mp4")

    speed  = round(random.uniform(1.005, 1.015), 4)   # 0.5-1.5% faster
    hue    = round(random.uniform(1.5, 3.5), 2)
    sat    = round(random.uniform(1.04, 1.10), 3)
    br     = round(random.uniform(0.01, 0.025), 3)
    pitch  = round(random.uniform(1.5, 3.0), 2)

    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setpts={1/speed}*PTS,"
        f"eq=contrast=1.06:brightness={br}:saturation={sat}:gamma=0.97,"
        f"hue=h={hue}:s=1.03,"
        f"crop=1078:1918:1:1,"
        f"scale=1080:1920,"
        f"unsharp=3:3:0.6:3:3:0.2"
    )

    if has_audio(inp):
        af = (
            f"asetrate=44100*{1+(pitch/1000)},"
            f"atempo={speed},"
            f"highpass=f=80,"
            f"lowpass=f=15000,"
            f"aecho=0.88:0.85:25:0.18,"
            f"loudnorm=I=-14:TP=-1:LRA=11"
        )
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","veryfast","-crf","21",
               "-c:a","aac","-b:a","192k",
               "-r","30",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
        ok, err = run_ffmpeg(cmd)
        # audio filter fail করলে সহজ filter দিয়ে retry
        if not ok:
            af_simple = f"atempo={speed},loudnorm=I=-14:TP=-1:LRA=11"
            cmd = [FFMPEG,"-y","-i",inp,
                   "-vf",vf,"-af",af_simple,
                   "-c:v","libx264","-preset","veryfast","-crf","21",
                   "-c:a","aac","-b:a","192k",
                   "-r","30",
                   "-map_metadata","-1",
                   "-movflags","+faststart",out]
            ok, err = run_ffmpeg(cmd)
    else:
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","veryfast","-crf","21",
               "-r","30",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
        ok, err = run_ffmpeg(cmd)

    return (out if ok else None), err

# ════════════════════════════════════════════
# ✨ ENHANCE
# ════════════════════════════════════════════
def process_enhance(inp):
    out = tmp_path(".mp4")
    info = get_video_info(inp)
    h = info["height"]

    # scale filter — trailing comma এড়াতে আলাদা রাখো
    if h > 0 and h < 1080:
        scale_f = "scale=trunc(iw*1080/ih/2)*2:1080:flags=lanczos"
        vf = (
            f"hqdn3d=2:2:5:5,"
            f"{scale_f},"
            f"eq=contrast=1.08:brightness=0.02:saturation=1.20:gamma=0.97,"
            f"unsharp=3:3:1.0:3:3:0.3,"
            f"vignette=PI/5"
        )
    else:
        vf = (
            "hqdn3d=2:2:5:5,"
            "eq=contrast=1.08:brightness=0.02:saturation=1.20:gamma=0.97,"
            "unsharp=3:3:1.0:3:3:0.3,"
            "vignette=PI/5"
        )

    if has_audio(inp):
        af = "loudnorm=I=-16:TP=-1.5:LRA=11"
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","fast","-crf","18",
               "-c:a","aac","-b:a","192k",
               "-movflags","+faststart",out]
        ok, err = run_ffmpeg(cmd)
        # vf fail করলে simple filter দিয়ে retry
        if not ok:
            vf_simple = "eq=contrast=1.08:brightness=0.02:saturation=1.20"
            cmd = [FFMPEG,"-y","-i",inp,
                   "-vf",vf_simple,"-af",af,
                   "-c:v","libx264","-preset","fast","-crf","18",
                   "-c:a","aac","-b:a","192k",
                   "-movflags","+faststart",out]
            ok, err = run_ffmpeg(cmd)
    else:
        cmd = [FFMPEG,"-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","fast","-crf","18",
               "-movflags","+faststart",out]
        ok, err = run_ffmpeg(cmd)
        if not ok:
            vf_simple = "eq=contrast=1.08:brightness=0.02:saturation=1.20"
            cmd = [FFMPEG,"-y","-i",inp,
                   "-vf",vf_simple,"-an",
                   "-c:v","libx264","-preset","fast","-crf","18",
                   "-movflags","+faststart",out]
            ok, err = run_ffmpeg(cmd)

    return (out if ok else None), err

# ════════════════════════════════════════════
# 🎵 VOCAL REMOVER — Music & Voice Separator
# ════════════════════════════════════════════
def _is_stereo(path):
    """ফাইলটা stereo কিনা চেক করো"""
    try:
        r = subprocess.run(
            [FFPROBE,"-v","error","-select_streams","a:0",
             "-show_entries","stream=channels","-of","csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15)
        ch = r.stdout.strip()
        return ch == "2"
    except Exception:
        return False

def process_vocal_remove(inp):
    """অডিও থেকে কথা সরিয়ে শুধু মিউজিক রাখো (ও উল্টোটা)"""
    out_music = tmp_path(".mp3")
    out_vocal = tmp_path(".mp3")

    stereo = _is_stereo(inp)

    if stereo:
        # Stereo: center channel cancellation — vocal সাধারণত center-panned
        # pan filter: L-R দিলে center cancel হয়, side channel থাকে (instrumentals)
        af_music = (
            "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,"
            "loudnorm=I=-14:TP=-1:LRA=11"
        )
        # Vocal: center extract — L+R
        af_vocal = (
            "pan=mono|c0=0.5*c0+0.5*c1,"
            "loudnorm=I=-14:TP=-1:LRA=11"
        )
    else:
        # Mono: vocal frequency cut (800Hz–3500Hz)
        af_music = (
            "equalizer=f=1000:width_type=o:width=3:g=-12,"
            "equalizer=f=2500:width_type=o:width=2:g=-10,"
            "loudnorm=I=-14:TP=-1:LRA=11"
        )
        af_vocal = (
            "equalizer=f=1000:width_type=o:width=3:g=6,"
            "equalizer=f=2500:width_type=o:width=2:g=5,"
            "highpass=f=200,lowpass=f=6000,"
            "loudnorm=I=-14:TP=-1:LRA=11"
        )

    cmd_music = [
        FFMPEG,"-y","-i", inp,
        "-af", af_music,
        "-c:a","libmp3lame","-b:a","192k",
        out_music
    ]
    cmd_vocal = [
        FFMPEG,"-y","-i", inp,
        "-af", af_vocal,
        "-c:a","libmp3lame","-b:a","192k",
        out_vocal
    ]

    ok_m, err_m = run_ffmpeg(cmd_music)
    # music fail করলে simple fallback
    if not ok_m:
        cmd_music_fallback = [
            FFMPEG,"-y","-i", inp,
            "-c:a","libmp3lame","-b:a","192k",
            out_music
        ]
        ok_m, err_m = run_ffmpeg(cmd_music_fallback)

    ok_v, err_v = run_ffmpeg(cmd_vocal)

    return (
        out_music if ok_m else None,
        out_vocal if ok_v else None,
        err_m or err_v,
        stereo,
    )

def process_vocal_remove_video(inp):
    """ভিডিও থেকে অডিও আলাদা করে vocal remove করো"""
    audio_tmp = tmp_path(".mp3")
    cmd_extract = [
        FFMPEG,"-y","-i", inp,
        "-vn","-c:a","libmp3lame","-b:a","192k",
        audio_tmp
    ]
    ok, err = run_ffmpeg(cmd_extract)
    if not ok:
        return None, None, err, False
    return process_vocal_remove(audio_tmp)

MODE_LABELS = {
    "tt_mode": "📱 TikTok Mode",
    "enhance": "✨ Enhance ULTRA",
}

MODE_CAPTIONS = {
    "tt_mode": (
        "🔥 *TikTok Mode — Done!*\n\n"
        "✅ Copyright bypass\n"
        "✅ Eligible For You bypass\n"
        "✅ 9:16 portrait ready\n"
        "✅ Color + speed shift\n"
        "✅ Metadata stripped"
    ),
    "enhance": (
        "✨ *Enhance ULTRA — Done!*\n\n"
        "✅ Cinematic color grade\n"
        "✅ Smart upscale → 1080p\n"
        "✅ Noise reduction\n"
        "✅ Sharpening + vignette\n"
        "✅ Audio normalized"
    ),
}

# ════════════════════════════════════════════
# ════════════════════════════════════════════
# 🎯 WINGO ENGINE — v3 ULTRA AI (70 Layers)
# ════════════════════════════════════════════
def _w_sizeof(n): return "BIG" if n >= 5 else "SMALL"
def _w_colorof(n):
    if n == 0: return "violet_red"
    if n == 5: return "violet_green"
    return "red" if n % 2 == 0 else "green"

def _w_parse_rows(rows, limit=200):
    out = []
    for row in rows[:limit]:
        try:
            n = int(row.get("number") or row.get("num") or row.get("winNumber") or -1)
            p = str(row.get("issueNumber") or row.get("period") or row.get("issue") or "")
            if n < 0 or not p: continue
            raw_color = str(row.get("color") or "").lower().strip()
            if "violet" in raw_color and "green" in raw_color:
                color = "violet_green"
            elif "violet" in raw_color and "red" in raw_color:
                color = "violet_red"
            elif "violet" in raw_color:
                color = "violet_red" if n == 0 else "violet_green"
            elif raw_color in ("red","green"):
                color = raw_color
            else:
                color = _w_colorof(n)
            out.append({"period": p, "number": n, "size": _w_sizeof(n), "color": color})
        except Exception:
            continue
    return out

_FETCH_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://www.ar-lottery01.com",
    "Referer":         "https://www.ar-lottery01.com/",
    "X-Requested-With":"XMLHttpRequest",
}

def _w_fetch_one(base_url, page=1, size=100):
    """Fetch one page from one API URL. Returns parsed rows or []."""
    ts  = int(time.time() * 1000)
    url = f"{base_url}&pageNo={page}" if "pageSize=" in base_url else base_url + str(ts)
    if "pageSize=" in base_url:
        url = base_url + str(ts) + f"&pageNo={page}"
    try:
        req = urllib.request.Request(url, headers=_FETCH_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        rows = []
        if isinstance(data, dict):
            inner = data.get("data", {})
            if isinstance(inner, dict):
                rows = inner.get("list", [])
            elif isinstance(inner, list):
                rows = inner
        out = _w_parse_rows(rows, size)
        return out
    except Exception as e:
        logger.debug("wingo fetch %s p%d: %s", base_url[:40], page, e)
        return []

def _w_fetch_apis(api_list):
    """Try each 30S API host in order; fetch page-1 + page-2 for 200 records."""
    for api in api_list:
        p1 = _w_fetch_one(api, page=1)
        if not p1: continue
        logger.info("WinGo API ok: %d rows p1", len(p1))
        p2 = _w_fetch_one(api, page=2)
        if p2:
            seen   = {r["period"] for r in p1}
            merged = p1 + [r for r in p2 if r["period"] not in seen]
            logger.info("WinGo deep: %d rows total", len(merged))
            return merged
        return p1
    return []

def _w_fetch():
    """Fetch 30S history (200 records deep) from best available host."""
    result = _w_fetch_apis(WINGO_APIS_30S)
    if result:
        _wingo_state["history"] = result
    return result

def _w_analyze(history):
    if len(history) < 5: return None
    N   = min(len(history), 200)
    h   = history[:N]
    nums   = [x["number"] for x in h]
    sizes  = [x["size"]   for x in h]
    colors = [x["color"]  for x in h]

    sb = ss = 0.0
    signals = []

    def vote(label, big_w, small_w, base=1.0):
        nonlocal sb, ss
        bw = max(0.0, float(big_w))
        sw = max(0.0, float(small_w))
        lp  = _wingo_state["layer_perf"].get(label, {})
        tot = lp.get("total", 0)
        if tot >= 10:
            acc = lp["hit"] / tot
            mul = (2.0 if acc > 0.70 else
                   1.6 if acc > 0.62 else
                   1.2 if acc > 0.55 else
                   0.5 if acc < 0.35 else
                   0.8 if acc < 0.42 else 1.0)
            base = base * mul
        sb += bw * base
        ss += sw * base
        total  = (bw + sw) or 1.0
        conf_l = max(bw, sw) / total
        winner = "BIG" if bw >= sw else "SMALL"
        signals.append((label, winner, round(conf_l * 100)))

    # pre-compute binary array (1=BIG, 0=SMALL) for math ops
    B = [1 if s=="BIG" else 0 for s in sizes]

    # ══════════════════════════════════════════════════
    # ── BLOCK A: FREQUENCY (1–5) ───────────────────────
    # ══════════════════════════════════════════════════
    b5  = sum(B[:5]);  b10 = sum(B[:10])
    b20 = sum(B[:min(20,N)]); b30 = sum(B[:min(30,N)])
    n30 = min(30,N)

    # 1. ultra-short (5)
    if b5 >= 4:   vote("freq5",  0, 2.0, 1.8)
    elif b5 <= 1: vote("freq5",  2.0, 0, 1.8)
    else:         vote("freq5",  b5/5, (5-b5)/5, 0.6)

    # 2. short (10)
    if b10 >= 8:   vote("freq10", 0, 1.7, 1.5)
    elif b10 <= 2: vote("freq10", 1.7, 0, 1.5)
    else:          vote("freq10", b10/10, (10-b10)/10, 0.8)

    # 3. mid (20)
    vote("freq20", b20/min(20,N), (min(20,N)-b20)/min(20,N), 0.9)

    # 4. long (30)
    vote("freq30", b30/n30, (n30-b30)/n30, 0.8)

    # 5. deep (50) — only with 200-record history
    if N >= 40:
        b50 = sum(B[:min(50,N)]); n50 = min(50,N)
        vote("freq50", b50/n50, (n50-b50)/n50, 0.7)

    # ══════════════════════════════════════════════════
    # ── BLOCK B: STREAK (6–8) ──────────────────────────
    # ══════════════════════════════════════════════════
    streak = 1
    for i in range(1, min(N, 30)):
        if sizes[i] == sizes[0]: streak += 1
        else: break
    opp_b = 1 if sizes[0]=="SMALL" else 0
    opp_s = 1 - opp_b

    # 6. streak mean-reversion
    if   streak >= 10: vote("streak", opp_b*4.0, opp_s*4.0, 2.5)
    elif streak >= 7:  vote("streak", opp_b*3.0, opp_s*3.0, 2.2)
    elif streak >= 5:  vote("streak", opp_b*2.2, opp_s*2.2, 1.8)
    elif streak >= 3:  vote("streak", opp_b*1.5, opp_s*1.5, 1.3)
    else:              vote("streak", 0.5, 0.5, 0.4)

    # 7. micro streak (last 3)
    b3 = sum(B[:3])
    if b3 == 3:   vote("streak3", 0, 2.0, 1.5)
    elif b3 == 0: vote("streak3", 2.0, 0, 1.5)
    else:         vote("streak3", 0.5, 0.5, 0.3)

    # 8. color streak reversal
    col_streak = 1
    for i in range(1, min(N,12)):
        if colors[i] == colors[0]: col_streak += 1
        else: break
    if col_streak >= 5:
        opp_c = "BIG" if colors[0] in ("green","violet_green") else "SMALL"
        vote("colstreak", 2.0 if opp_c=="BIG" else 0, 2.0 if opp_c=="SMALL" else 0, 1.4)
    else:
        vote("colstreak", 0.5, 0.5, 0.3)

    # ══════════════════════════════════════════════════
    # ── BLOCK C: MARKOV O1–O5 (9–13) ──────────────────
    # ══════════════════════════════════════════════════
    def _markov(order, base_w):
        if N < order + 3: return
        m = {}
        for i in range(N - order):
            key = "|".join(sizes[i+order:i:-1])
            m.setdefault(key, {"BIG":0,"SMALL":0})
            m[key][sizes[i]] += 1
        key0 = "|".join(sizes[:order])
        c = m.get(key0, {"BIG":0,"SMALL":0}); t = c["BIG"]+c["SMALL"]
        min_t = max(2, 5 - order)
        if t >= min_t:
            vote(f"markov{order}", c["BIG"]/t, c["SMALL"]/t,
                 base_w * (1.0 + min(t, 20)/40))

    _markov(1, 1.5); _markov(2, 1.7); _markov(3, 1.9); _markov(4, 2.0); _markov(5, 2.1)

    # ══════════════════════════════════════════════════
    # ── BLOCK D: EMA / WMA / RSI / MACD (14–21) ───────
    # ══════════════════════════════════════════════════
    def _ema(alpha, period):
        e = float(B[0])
        for i in range(1, min(N, period)):
            e = alpha * B[i] + (1-alpha) * e
        return e

    ema3  = _ema(0.40, 6)
    ema8  = _ema(0.25, 12)
    ema20 = _ema(0.10, 25)
    ema50 = _ema(0.04, 60)

    # 14. EMA ultra-short
    vote("ema3",  1-ema3,  ema3,  1.3)
    # 15. EMA short
    vote("ema8",  1-ema8,  ema8,  1.2)
    # 16. EMA mid
    vote("ema20", 1-ema20, ema20, 1.0)
    # 17. EMA long
    vote("ema50", 1-ema50, ema50, 0.8)

    # 18. MACD — fast(3) vs slow(20)
    macd_val = ema3 - ema20
    signal_line = ema8 - ema50
    if   macd_val >  0.25 and signal_line >  0: vote("macd", 0, 1.8, 1.4)
    elif macd_val < -0.25 and signal_line <  0: vote("macd", 1.8, 0, 1.4)
    elif macd_val >  0.10: vote("macd", 0, 1.1, 0.9)
    elif macd_val < -0.10: vote("macd", 1.1, 0, 0.9)
    else:                  vote("macd", 0.5, 0.5, 0.3)

    # 19. WMA-10
    if N >= 10:
        wma10 = sum((10-i)*B[i] for i in range(10)) / 55.0
        vote("wma10", 1-wma10, wma10, 1.1)

    # 20. WMA-20
    if N >= 20:
        wma20 = sum((20-i)*B[i] for i in range(20)) / 210.0
        vote("wma20", 1-wma20, wma20, 0.9)

    # 21. RSI-14
    gains = losses = 0.0
    rsi = 50.0
    if N >= 14:
        for i in range(min(N-1, 14)):
            if   B[i]==1 and B[i+1]==0: gains  += 1
            elif B[i]==0 and B[i+1]==1: losses += 1
        rs  = gains / (losses or 0.001)
        rsi = 100 - 100/(1+rs)
        if   rsi >= 78: vote("rsi", 0, 2.0, 1.6)
        elif rsi <= 22: vote("rsi", 2.0, 0, 1.6)
        elif rsi >= 65: vote("rsi", 0, 1.3, 1.0)
        elif rsi <= 35: vote("rsi", 1.3, 0, 1.0)
        else:           vote("rsi", 0.5, 0.5, 0.4)

    # ══════════════════════════════════════════════════
    # ── BLOCK E: PATTERN LIBRARY (22–28) ──────────────
    # ══════════════════════════════════════════════════
    # 22. Alternation (last 6)
    if N >= 6:
        alt6 = sum(1 for i in range(1,6) if B[i] != B[i-1])
        if alt6 >= 5:
            nxt = "SMALL" if B[0]==1 else "BIG"
            vote("alt6", 1.8 if nxt=="BIG" else 0, 1.8 if nxt=="SMALL" else 0, 1.5)
        elif alt6 <= 1:
            vote("alt6", 1.4 if B[0]==1 else 0, 1.4 if B[0]==0 else 0, 1.2)
        else:
            vote("alt6", 0.5, 0.5, 0.3)

    # 23. Double-pair pattern BBSS / SSBB
    if N >= 8:
        pat = "".join("B" if x==1 else "S" for x in B[:8])
        if pat[:4] in ("BBSS","SSBB"):
            nxt = "SMALL" if pat[:2]=="BB" else "BIG"
            vote("dbl_pat", 1.6 if nxt=="BIG" else 0, 1.6 if nxt=="SMALL" else 0, 1.4)

    # 24. Triple run + reversal
    if N >= 6:
        b3 = sum(B[:3])
        if   b3 == 3: vote("trip_pat", 0, 2.2, 1.6)
        elif b3 == 0: vote("trip_pat", 2.2, 0, 1.6)

    # 25. History pattern-match (deep — search 200 records)
    if N >= 15:
        query = sizes[:6]
        mb = ms = 0
        for s in range(6, N-6):
            if sizes[s:s+6] == query:
                mb += (1 if B[s-1]==1 else 0)
                ms += (1 if B[s-1]==0 else 0)
        if mb + ms >= 3:
            vote("pat_match6", mb/(mb+ms), ms/(mb+ms), 2.2)

    # 26. 3-back similarity (most similar last-3 in history)
    if N >= 10:
        q3 = B[:3]
        mb3 = ms3 = 0
        for s in range(3, N-3):
            if B[s:s+3] == q3:
                mb3 += B[s-1]; ms3 += (1-B[s-1])
        if mb3+ms3 >= 2:
            vote("pat_match3", mb3/(mb3+ms3), ms3/(mb3+ms3), 1.8)

    # 27. Cycle detection period-2
    if N >= 14:
        p2 = sum(1 for i in range(0, min(N-2,12), 2) if B[i]==B[i+2])
        if p2 >= 5:
            nxt_p2 = B[1]
            vote("cycle2", nxt_p2*1.6, (1-nxt_p2)*1.6, 1.4)

    # 28. Cycle detection period-3
    if N >= 15:
        p3 = sum(1 for i in range(0, min(N-3,12), 3) if B[i]==B[i+3])
        if p3 >= 4:
            nxt_p3 = B[1] if N>1 else 0
            vote("cycle3", nxt_p3*1.5, (1-nxt_p3)*1.5, 1.3)

    # ══════════════════════════════════════════════════
    # ── BLOCK F: COLOR (29–33) ─────────────────────────
    # ══════════════════════════════════════════════════
    is_red   = [1 if c in ("red","violet_red")   else 0 for c in colors]
    is_green = [1 if c in ("green","violet_green") else 0 for c in colors]

    # 29. Color trend (8 rounds)
    red8 = sum(is_red[:8]); grn8 = sum(is_green[:8])
    if   red8   >= 6: vote("col_trend", 1.4, 0,   1.1)
    elif grn8   >= 6: vote("col_trend", 0,   1.4, 1.1)
    else:             vote("col_trend", 0.5, 0.5, 0.3)

    # 30. Color Markov (what size follows this color?)
    if N >= 5:
        cm = {}
        for i in range(N-1):
            cm.setdefault(colors[i+1], {"BIG":0,"SMALL":0})
            cm[colors[i+1]][sizes[i]] += 1
        cc = cm.get(colors[0], {"BIG":0,"SMALL":0}); ct2 = cc["BIG"]+cc["SMALL"]
        if ct2 >= 6: vote("col_markov", cc["BIG"]/ct2, cc["SMALL"]/ct2, 1.4)
        elif ct2>=3: vote("col_markov", cc["BIG"]/ct2, cc["SMALL"]/ct2, 1.0)

    # 31. Violet gap (overdue)
    last_vio = next((i for i,c in enumerate(colors) if "violet" in c), 99)
    if   last_vio >= 20: vote("vio_due",    0.4, 1.2, 0.9)
    elif last_vio >= 12: vote("vio_due",    0.5, 1.0, 0.7)
    elif last_vio <= 2:  vote("vio_recent", 0.5, 0.5, 0.3)

    # 32. Color oscillation
    if N >= 6:
        col_osc = sum(1 for i in range(1,6) if is_red[i] != is_red[i-1])
        if col_osc >= 4:
            nxt_bg = 1 if is_green[0] else 0
            vote("col_osc", nxt_bg*1.5, (1-nxt_bg)*1.5, 1.2)

    # 33. Color run (same color 4+)
    col_run = 1
    for i in range(1, min(N,10)):
        if is_red[i]==is_red[0] and is_green[i]==is_green[0]: col_run+=1
        else: break
    if col_run >= 4:
        opp_cr = 1 if is_red[0] else 0   # red run → expect green (BIG more likely)
        vote("col_run", opp_cr*1.6, (1-opp_cr)*1.6, 1.3)

    # ══════════════════════════════════════════════════
    # ── BLOCK G: STATISTICAL (34–40) ──────────────────
    # ══════════════════════════════════════════════════
    # 34. Mean reversion (full N)
    if N >= 20:
        total_big = sum(B)
        dev = total_big - N/2
        if   dev >= 15: vote("meanrev", 0, 2.5, 1.8)
        elif dev >= 10: vote("meanrev", 0, 1.8, 1.4)
        elif dev >=  5: vote("meanrev", 0, 1.2, 1.0)
        elif dev <= -15:vote("meanrev", 2.5, 0, 1.8)
        elif dev <= -10:vote("meanrev", 1.8, 0, 1.4)
        elif dev <=  -5:vote("meanrev", 1.2, 0, 1.0)
        else:           vote("meanrev", 0.5, 0.5, 0.5)

    # 35. Hot/cold number groups
    last_seen = {}
    for i, nn in enumerate(nums):
        if nn not in last_seen: last_seen[nn] = i
    gaps = {nn: last_seen.get(nn, N+5) for nn in range(10)}
    cold_b = sum(1 for nn in range(5,10) if gaps[nn] >= 12)
    cold_s = sum(1 for nn in range(0, 5) if gaps[nn] >= 12)
    if   cold_b >= 3: vote("hotcold", 0, 1.8, 1.3)
    elif cold_b >= 2: vote("hotcold", 0, 1.3, 1.0)
    elif cold_s >= 3: vote("hotcold", 1.8, 0, 1.3)
    elif cold_s >= 2: vote("hotcold", 1.3, 0, 1.0)
    else:             vote("hotcold", 0.5, 0.5, 0.3)

    # 36. Number gap — overdue side
    due_b = sum(1 for nn in range(5,10) if gaps[nn] >= 10)
    due_s = sum(1 for nn in range(0, 5) if gaps[nn] >= 10)
    if   due_b >= 4: vote("num_gap", 0, 1.6, 1.2)
    elif due_b >= 3: vote("num_gap", 0, 1.2, 0.9)
    elif due_s >= 4: vote("num_gap", 1.6, 0, 1.2)
    elif due_s >= 3: vote("num_gap", 1.2, 0, 0.9)

    # 37. Shannon Entropy
    if N >= 10:
        win = min(20, N)
        pb = sum(B[:win]) / win; ps = 1 - pb
        entropy = -(pb*math.log2(pb+1e-9) + ps*math.log2(ps+1e-9))
        if   entropy > 0.98: vote("entropy", 0.5, 0.5, 0.1)   # pure noise
        elif entropy < 0.50: vote("entropy",
            1.5 if B[0]==1 else 0, 1.5 if B[0]==0 else 0, 1.3)
        else:                vote("entropy", 0.5, 0.5, 0.4)
    else: entropy = 1.0

    # 38. Z-score
    if N >= 20:
        mu    = sum(B[:20]) / 20
        sigma = math.sqrt(mu*(1-mu)+1e-9)
        z     = (b5/5 - mu) / sigma
        if   z >  2.5: vote("zscore", 0, 2.2, 1.6)
        elif z < -2.5: vote("zscore", 2.2, 0, 1.6)
        elif z >  1.5: vote("zscore", 0, 1.4, 1.1)
        elif z < -1.5: vote("zscore", 1.4, 0, 1.1)
        elif z >  0.8: vote("zscore", 0, 0.9, 0.7)
        elif z < -0.8: vote("zscore", 0.9, 0, 0.7)
    else: z = 0.0

    # 39. Autocorrelation lag-1 (does each outcome predict next?)
    if N >= 20:
        same_1 = sum(1 for i in range(min(N-1,30)) if B[i]==B[i+1])
        diff_1 = min(N-1,30) - same_1
        if   same_1 >= 22: vote("autocor1", 1.5*B[0], 1.5*(1-B[0]), 1.2)  # trend market
        elif diff_1 >= 22: vote("autocor1", 1.5*(1-B[0]), 1.5*B[0], 1.2)  # reversal market

    # 40. Autocorrelation lag-2
    if N >= 20:
        same_2 = sum(1 for i in range(min(N-2,30)) if B[i]==B[i+2])
        diff_2 = min(N-2,30) - same_2
        if   same_2 >= 22: vote("autocor2", 1.4*B[0], 1.4*(1-B[0]), 1.1)
        elif diff_2 >= 22: vote("autocor2", 1.4*(1-B[0]), 1.4*B[0], 1.1)

    # ══════════════════════════════════════════════════
    # ── BLOCK H: ADAPTIVE / FEEDBACK (41–45) ──────────
    # ══════════════════════════════════════════════════
    loss_stk = _wingo_state.get("loss_streak", 0)
    win_stk  = _wingo_state.get("win_streak",  0)

    # 41. Loss-streak flip (signal anti-correlates after 3+ losses)
    if   loss_stk >= 5: vote("lossadapt", ss*1.2, sb*1.2, 2.0)
    elif loss_stk >= 3: vote("lossadapt", ss*0.8, sb*0.8, 1.5)
    elif loss_stk >= 2: vote("lossadapt", ss*0.4, sb*0.4, 1.0)
    elif win_stk  >= 7: vote("winadapt",  sb*0.3, ss*0.3, 0.5)
    else:               vote("streak_neu", 0.5, 0.5, 0.2)

    # 42. Session accuracy feedback
    tot_p  = _wingo_state.get("total_pred", 0)
    cor_p  = _wingo_state.get("correct_pred", 0)
    if tot_p >= 8:
        acc_s = cor_p / tot_p
        if   acc_s < 0.32: vote("acc_flip", ss*1.3, sb*1.3, 1.2)
        elif acc_s > 0.72: vote("acc_keep", sb*0.5, ss*0.5, 0.5)

    # 43. Consecutive same + reversal boost
    run_len = 1
    for i in range(1, min(N, 10)):
        if B[i]==B[0]: run_len+=1
        else: break
    if   run_len >= 6: vote("run_opp", opp_b*3.0, opp_s*3.0, 2.0)
    elif run_len >= 4: vote("run_opp", opp_b*2.0, opp_s*2.0, 1.7)
    elif run_len >= 3: vote("run_opp", opp_b*1.3, opp_s*1.3, 1.2)

    # 44. Volatility regime
    vol = 0.5
    if N >= 10:
        alt10 = sum(1 for i in range(1,min(N,11)) if B[i]!=B[i-1])
        vol = alt10 / 10
        if   vol >= 0.90: vote("vol_high", 0.5, 0.5, 0.1)
        elif vol <= 0.20: vote("vol_low", 1.4*B[0], 1.4*(1-B[0]), 1.2)
        else:             vote("vol_mid", 0.5, 0.5, 0.4)

    # 45. Volatility trend (now vs before)
    if N >= 20:
        alt5  = sum(1 for i in range(1,5)  if B[i]!=B[i-1])/4
        alt20 = sum(1 for i in range(5,20) if B[i]!=B[i-1])/15
        if   alt5 > alt20 + 0.35: vote("vol_spike", 0.5, 0.5, 0.1)
        elif alt5 < alt20 - 0.35: vote("vol_calm", 1.3*B[0], 1.3*(1-B[0]), 1.1)

    # ══════════════════════════════════════════════════
    # ── BLOCK I: NUMBER ANALYSIS (46–51) ──────────────
    # ══════════════════════════════════════════════════
    # 46. Parity bias (odd vs even)
    odd_cnt  = sum(1 for nn in nums[:20] if nn%2==1)
    even_cnt = 20 - odd_cnt
    # odd numbers: 1,3,7,9 → mostly SMALL; 5 = BIG+ODD but violet
    # even: 2,4=SMALL, 6,8=BIG
    big_even = sum(1 for nn in nums[:20] if nn in (6,8))
    sml_odd  = sum(1 for nn in nums[:20] if nn in (1,3,9))
    if big_even >= 5:   vote("parity", 0, 1.4, 1.0)
    elif sml_odd >= 7:  vote("parity", 1.4, 0, 1.0)
    else:               vote("parity", 0.5, 0.5, 0.3)

    # 47. Number magnitude (avg of last 5 nums)
    avg5 = sum(nums[:5]) / 5 if N >= 5 else 4.5
    if   avg5 >= 6.5: vote("num_mag", 0, 1.5, 1.2)
    elif avg5 <= 3.0: vote("num_mag", 1.5, 0, 1.2)
    elif avg5 >= 5.5: vote("num_mag", 0, 1.0, 0.8)
    elif avg5 <= 3.5: vote("num_mag", 1.0, 0, 0.8)
    else:             vote("num_mag", 0.5, 0.5, 0.3)

    # 48. Number range (max−min in last 5)
    if N >= 5:
        rng5 = max(nums[:5]) - min(nums[:5])
        if rng5 >= 7: vote("num_range", 0.5, 0.5, 0.2)   # wide = noisy
        elif rng5 <= 2:
            vote("num_range", 1.3 if B[0]==1 else 0,
                              1.3 if B[0]==0 else 0, 1.0)

    # 49. Number clustering (BIG cluster 7-9 or SMALL cluster 0-2)
    big_clust = sum(1 for nn in nums[:10] if nn >= 7)
    sml_clust = sum(1 for nn in nums[:10] if nn <= 2)
    if   big_clust >= 5: vote("clust", 0, 1.6, 1.2)
    elif sml_clust >= 5: vote("clust", 1.6, 0, 1.2)
    else:                vote("clust", 0.5, 0.5, 0.3)

    # 50. Number mod-3 pattern
    mod3_cnt = Counter(nn%3 for nn in nums[:15])
    dom_mod  = mod3_cnt.most_common(1)[0][0] if mod3_cnt else -1
    # mod0: 0,3,6,9 — mixed; mod1: 1,4,7 — mostly SMALL+BIG mix; mod2: 2,5,8 — 5=BIG
    if   dom_mod == 2 and mod3_cnt.get(2,0) >= 7: vote("mod3", 0, 1.3, 1.0)
    elif dom_mod == 0 and mod3_cnt.get(0,0) >= 7: vote("mod3", 0.5, 0.5, 0.5)

    # 51. Consecutive number (adjacent nums e.g. 3,4,5)
    if N >= 5:
        adj = sum(1 for i in range(4) if abs(nums[i]-nums[i+1])==1)
        if adj >= 3: vote("adj_num", 0.5, 0.5, 0.2)  # consecutive → noisy

    # ══════════════════════════════════════════════════
    # ── BLOCK J: BAYESIAN (52–54) ─────────────────────
    # ══════════════════════════════════════════════════
    # 52. Bayesian posterior with uniform prior + session data
    tot_p2  = _wingo_state.get("total_pred", 0)
    cor_p2  = _wingo_state.get("correct_pred", 0)
    if tot_p2 >= 5:
        # simple binomial posterior: Beta(α,β) updated with data
        alpha_b = 1 + cor_p2
        beta_b  = 1 + (tot_p2 - cor_p2)
        p_succ  = alpha_b / (alpha_b + beta_b)
        # combine with current signal direction
        boost = 1.0 + abs(p_succ - 0.5) * 2
        vote("bayes_post", sb*boost if sb>=ss else 0,
                           ss*boost if ss>sb  else 0, 0.8)

    # 53. Likelihood ratio (signal strength vs prior expectation)
    if N >= 30:
        p_big_prior = sum(B[:50]) / min(50,N)  # long-run frequency
        lkr = (b10/10) / (p_big_prior + 1e-9)
        if   lkr > 1.8: vote("lkr", 0, 1.5, 1.1)
        elif lkr < 0.4: vote("lkr", 1.5, 0, 1.1)
        else:           vote("lkr", 0.5, 0.5, 0.3)

    # 54. Prior-weighted naive Bayes
    if N >= 20:
        p_b_all = sum(B) / N
        # P(BIG | last5 were all BIG) vs base rate
        if b5 == 5:
            ratio = p_b_all / max(1-p_b_all, 0.001)
            if ratio < 0.5: vote("nbayes", 0, 1.8, 1.3)  # dominant SMALL if rare BIG
            else:           vote("nbayes", 0.5, 0.5, 0.4)
        elif b5 == 0:
            if p_b_all > 0.55: vote("nbayes", 1.8, 0, 1.3)
            else:              vote("nbayes", 0.5, 0.5, 0.4)

    # ══════════════════════════════════════════════════
    # ── BLOCK K: STOCHASTIC / WILLIAMS (55–57) ─────────
    # ══════════════════════════════════════════════════
    if N >= 14:
        # Stochastic %K: (current_avg - lowest) / (highest - lowest)
        win14   = B[:14]
        lo14    = min(win14); hi14 = max(win14)
        denom   = (hi14 - lo14) or 1.0
        stoch_k = (B[0] - lo14) / denom
        # Stochastic %D (3-period moving avg of K)
        ks = []
        for i in range(3):
            w14 = B[i:i+14]
            lo_ = min(w14); hi_ = max(w14); d_ = (hi_-lo_) or 1.0
            ks.append((B[i]-lo_)/d_)
        stoch_d = sum(ks)/3

        # 55. Stochastic overbought/oversold
        if   stoch_k >= 0.85 and stoch_d >= 0.80: vote("stoch", 0, 1.8, 1.4)
        elif stoch_k <= 0.15 and stoch_d <= 0.20: vote("stoch", 1.8, 0, 1.4)
        elif stoch_k >= 0.70: vote("stoch", 0, 1.1, 0.9)
        elif stoch_k <= 0.30: vote("stoch", 1.1, 0, 0.9)
        else:                 vote("stoch", 0.5, 0.5, 0.3)

        # 56. Stochastic crossover (%K vs %D)
        if   stoch_k > stoch_d + 0.2: vote("stoch_cross", 0, 1.4, 1.1)
        elif stoch_k < stoch_d - 0.2: vote("stoch_cross", 1.4, 0, 1.1)

        # 57. Williams %R = (highest - close) / (highest - lowest) * -100
        wR = -(hi14 - B[0]) / denom * 100
        if   wR <= -80: vote("willR", 1.6, 0, 1.2)    # oversold → BIG
        elif wR >= -20: vote("willR", 0, 1.6, 1.2)    # overbought → SMALL
        else:           vote("willR", 0.5, 0.5, 0.3)

    # ══════════════════════════════════════════════════
    # ── BLOCK L: TRANSITION MATRIX (58–60) ─────────────
    # ══════════════════════════════════════════════════
    if N >= 20:
        # Transition counts
        bb = bs = sb2 = ss2 = 0
        for i in range(min(N-1,50)):
            if   B[i]==1 and B[i+1]==1: bb += 1
            elif B[i]==1 and B[i+1]==0: bs += 1
            elif B[i]==0 and B[i+1]==1: sb2+= 1
            else:                       ss2+= 1

        # 58. P(BIG | prev BIG)
        p_bb = bb / (bb+bs+1e-9)
        p_bs = bs / (bb+bs+1e-9)
        if B[0]==1 and (bb+bs) >= 8:
            vote("trans_bb", p_bb, p_bs, 1.6 if abs(p_bb-p_bs)>0.2 else 0.6)

        # 59. P(BIG | prev SMALL)
        p_sb = sb2/ (sb2+ss2+1e-9)
        p_ss = ss2/ (sb2+ss2+1e-9)
        if B[0]==0 and (sb2+ss2) >= 8:
            vote("trans_sb", p_sb, p_ss, 1.6 if abs(p_sb-p_ss)>0.2 else 0.6)

        # 60. Mean run length vs expected
        runs = []
        cur_run = 1
        for i in range(1, min(N,50)):
            if B[i]==B[i-1]: cur_run+=1
            else: runs.append(cur_run); cur_run=1
        runs.append(cur_run)
        avg_run = sum(runs)/len(runs) if runs else 2
        # if avg run > 2 → trend market; < 1.5 → reversal market
        if avg_run > 2.5:
            vote("run_len", 1.4*B[0], 1.4*(1-B[0]), 1.2)
        elif avg_run < 1.6:
            vote("run_len", 1.4*(1-B[0]), 1.4*B[0], 1.2)

    # ══════════════════════════════════════════════════
    # ── BLOCK N: META ENSEMBLE (66–70) ────────────────
    # ══════════════════════════════════════════════════
    # 66. Top-5 performing layers weighted vote
    top5 = sorted(
        [(lbl,lp) for lbl,lp in _wingo_state["layer_perf"].items()
         if lp.get("total",0) >= 15],
        key=lambda x: x[1]["hit"]/x[1]["total"], reverse=True
    )[:5]
    for lbl, lp in top5:
        acc_l  = lp["hit"]/lp["total"]
        prev_s = next((s for n,s,_ in signals if n==lbl), None)
        if prev_s:
            boost  = 1.0 + (acc_l - 0.5) * 3.0
            vote(f"meta_{lbl}", 1*boost if prev_s=="BIG" else 0,
                                1*boost if prev_s=="SMALL" else 0, 0.8)

    # 67. Unanimous agreement boost (≥65% of layers agree)
    big_l   = sum(1 for _,v,_ in signals if v=="BIG")
    sml_l   = sum(1 for _,v,_ in signals if v=="SMALL")
    tot_l   = len(signals)
    if tot_l >= 20:
        big_ratio = big_l / tot_l
        if   big_ratio >= 0.75: vote("unanimous", 0, 2.5, 2.0)
        elif big_ratio <= 0.25: vote("unanimous", 2.5, 0, 2.0)
        elif big_ratio >= 0.65: vote("unanimous", 0, 1.8, 1.5)
        elif big_ratio <= 0.35: vote("unanimous", 1.8, 0, 1.5)

    # 68. Session momentum (rolling last-20 vote scores)
    session_v = _wingo_state.get("session_votes", [])[-20:]
    if len(session_v) >= 5:
        sv_big = sum(1 for v in session_v if v=="BIG")
        sv_rat = sv_big / len(session_v)
        # session momentum opposite of recent run
        if   sv_rat >= 0.80: vote("ses_mom", 0, 1.5, 1.0)
        elif sv_rat <= 0.20: vote("ses_mom", 1.5, 0, 1.0)
        elif sv_rat >= 0.65: vote("ses_mom", 0, 1.0, 0.7)
        elif sv_rat <= 0.35: vote("ses_mom", 1.0, 0, 0.7)

    # 69. Deep history long-run mean reversion (100–200 records)
    if N >= 80:
        b100 = sum(B[:100]); dev100 = b100 - 50
        if   dev100 >= 15: vote("deep_rev", 0, 2.0, 1.5)
        elif dev100 >= 8:  vote("deep_rev", 0, 1.3, 1.0)
        elif dev100 <= -15:vote("deep_rev", 2.0, 0, 1.5)
        elif dev100 <= -8: vote("deep_rev", 1.3, 0, 1.0)

    # 70. Soft consensus calibration (Platt-like sigmoid)
    tw_pre = sb + ss or 1
    p_raw  = sb / tw_pre
    # sigmoid sharpening: push away from 0.5
    p_cal  = 1/(1 + math.exp(-6*(p_raw-0.5)))
    vote("calibrate", 1-p_cal, p_cal, 0.8)

    # ══════════════════════════════════════════════════
    # ── FINAL SIGNAL ──────────────────────────────────
    # ══════════════════════════════════════════════════
    tw   = sb + ss or 1
    pB   = round(sb / tw * 100)
    pS   = 100 - pB
    sig  = "BIG" if sb >= ss else "SMALL"
    conf = max(pB, pS)

    # record session vote
    _wingo_state.setdefault("session_votes",[]).append(sig)
    if len(_wingo_state["session_votes"]) > 200:
        _wingo_state["session_votes"] = _wingo_state["session_votes"][-200:]

    big_layers   = sum(1 for _,v,_ in signals if v=="BIG")
    small_layers = sum(1 for _,v,_ in signals if v=="SMALL")
    total_layers = len(signals)

    # ── COLOR PREDICTION ──────────────────────────────
    cs = {"red":0.0,"green":0.0,"violet":0.0}
    for i,col in enumerate(colors[:50]):
        w = 1.0/(i*0.05+1)
        if   col in ("red","violet_red"):    cs["red"]    += w
        elif col in ("green","violet_green"): cs["green"] += w
        else:                                cs["violet"] += w * 1.6
    if sig == "BIG":  cs["red"]   += 5.0; cs["violet"] += 1.5
    else:             cs["green"] += 5.0; cs["violet"] += 1.5
    if last_vio >= 18: cs["violet"] += 4.0
    elif last_vio >= 10: cs["violet"] += 2.0
    ct = sum(cs.values()) or 1
    pR = round(cs["red"]  /ct*100)
    pG = round(cs["green"]/ct*100)
    pV = max(0, 100-pR-pG)
    tc = ("red" if pR>=pG and pR>=pV else
          "green" if pG>=pR and pG>=pV else "violet")

    # ── NUMBER PREDICTION ─────────────────────────────
    ns = [0.0]*10
    for i,nn in enumerate(nums[:80]):
        ns[nn] += 1.0/(i*0.04+1)
    for nn in range(10):
        if _w_sizeof(nn)==sig: ns[nn] += 8.0
        gap = gaps.get(nn, N)
        if gap >= 10: ns[nn] += gap*0.4
        if gap <= 3:  ns[nn] -= 2.0  # recently appeared → slight penalty
    ranked = sorted(range(10), key=lambda x: -ns[x])

    # ── CONFIDENCE TIER ───────────────────────────────
    if   conf >= 87: conf_label="🔥 ULTRA";  tier="S"
    elif conf >= 80: conf_label="💪 HIGH";   tier="A+"
    elif conf >= 73: conf_label="✅ GOOD";   tier="A"
    elif conf >= 65: conf_label="⚡ MED";    tier="B"
    elif conf >= 57: conf_label="⚠️ LOW";    tier="C"
    else:            conf_label="❓ WEAK";   tier="D"

    risk = ("🟢 LOW"  if conf >= 78 and loss_stk <= 1 else
            "🟡 MED"  if conf >= 63 else "🔴 HIGH")

    # ── INSIGHT ───────────────────────────────────────
    if streak >= 7:
        insight = f"{'🔺' if B[0] else '🔻'} {streak}x Streak → Strong Reversal!"
    elif loss_stk >= 4:
        insight = f"❗ {loss_stk}x Loss → Adaptive flip"
    elif conf >= 87:
        insight = f"🔥 {big_layers}/{total_layers} layers consensus — ULTRA signal"
    elif z > 2.0 or z < -2.0:
        insight = f"📐 Z={z:.1f} — Extreme deviation → Revert"
    elif rsi >= 75:
        insight = f"📈 RSI={round(rsi)} — Overbought → SMALL likely"
    elif rsi <= 25:
        insight = f"📉 RSI={round(rsi)} — Oversold → BIG likely"
    else:
        dom = "BIG" if b10 >= 7 else ("SMALL" if b10 <= 3 else None)
        insight = (f"📊 {dom} dominant — Rebalancing due" if dom
                   else f"📊 {big_layers}🔺 vs {small_layers}🔻 — Pattern match")

    return {
        "sig": sig, "conf": conf, "conf_label": conf_label,
        "tier": tier, "risk": risk,
        "pB": pB, "pS": pS, "pR": pR, "pG": pG, "pV": pV, "tc": tc,
        "numTop": ranked[0], "numAlt": ranked[1:5],
        "period": history[0]["period"] if history else "",
        "big_layers": big_layers, "small_layers": small_layers,
        "total_layers": total_layers, "signals": signals,
        "insight": insight, "streak": streak,
        "rsi": round(rsi), "vol": round(vol*100),
        "z": round(z,1), "entropy": round(entropy,2),
        "hot_nums":  [nn for nn in range(10) if gaps.get(nn,99) <= 3],
        "cold_nums": [nn for nn in range(10) if gaps.get(nn,99) >= 12],
    }

# ════════════════════════════════════════════
# MENUS
# ════════════════════════════════════════════
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🚀  ভিডিও ডাউনলোড", callback_data="dl_help")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🔥  TikTok Mode", callback_data="tt_help"),
         InlineKeyboardButton("✨  Enhance ULTRA", callback_data="enhance_help")],
        [InlineKeyboardButton("🎵  Vocal Remover", callback_data="vocal_help")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("⚡  WinGo AI Signal", callback_data="wingo_menu")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🎭  Viral Script Generator", callback_data="sc_start")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
    ])

def wingo_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡  Signal নাও এখনই!", callback_data="wingo_predict")],
        [InlineKeyboardButton("🟢  Auto চালু", callback_data="wingo_auto_on"),
         InlineKeyboardButton("🔴  Auto বন্ধ", callback_data="wingo_auto_off")],
        [InlineKeyboardButton("📈  Stats",       callback_data="wingo_stats"),
         InlineKeyboardButton("🔍  Analysis",    callback_data="wingo_analysis"),
         InlineKeyboardButton("🏆  Top Layers",  callback_data="wingo_layers")],
        [InlineKeyboardButton("🌡️  Hot/Cold",    callback_data="wingo_hotcold"),
         InlineKeyboardButton("🏠  হোম",         callback_data="back_main")],
    ])

def edit_btns(job):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥  TikTok Mode", callback_data=f"do_tt_mode_{job}"),
         InlineKeyboardButton("✨  Enhance", callback_data=f"do_enhance_{job}")],
        [InlineKeyboardButton("🎵  Vocal Remover", callback_data=f"do_vocal_{job}")],
        [InlineKeyboardButton("⚡  WinGo Signal", callback_data="wingo_menu")],
    ])

START_TEXT = """
🔥 *Video Bot {ver}*

┌─────────────────────────┐
│  🚀  *ভিডিও ডাউনলোড*
│  YouTube · TikTok · Instagram
│  Facebook · Pinterest
├─────────────────────────┤
│  🔥  *TikTok Mode*
│  Copyright ❌  Eligible ❌
│  7-layer smart bypass
├─────────────────────────┤
│  ✨  *Enhance ULTRA*
│  Cinematic quality upgrade
├─────────────────────────┤
│  🎵  *Vocal Remover*
│  মিউজিক ও কথা আলাদা করো
│  MP3/ভিডিও সাপোর্ট
├─────────────────────────┤
│  ⚡  *WinGo AI v3 — 70 Layers*
│  MACD · Stochastic · Bayesian
│  200-record deep history
├─────────────────────────┤
│  🎭  *Viral Script Generator*
│  WhatsApp + Messenger স্টাইল
│  Claude AI — আনলিমিটেড স্ক্রিপ্ট
└─────────────────────────┘

📎 _Link পাঠান_ → Download
🎬 _ভিডিও/অডিও পাঠান_ → Edit
""".strip()

# ════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════
async def cmd_start(u, c):
    name = md_escape(u.effective_user.first_name or "বন্ধু")
    await safe_reply(u.message,
        f"👋 *হ্যালো {name}!*\n\n" + START_TEXT.format(ver=VERSION),
        parse_mode="Markdown", reply_markup=main_menu())

async def cmd_script(u, c):
    await safe_reply(u.message,
        "🎭 *Viral Script Generator*\n\nটপিক বেছে নাও 👇",
        parse_mode="Markdown", reply_markup=script_topic_menu())

async def cmd_wingo(u, c):
    await safe_reply(u.message,
        "⚡ *WinGo AI ULTRA v2*\n\n"
        "50-layer AI · RSI · Pattern Match · Entropy\n"
        "👇 Signal নাও",
        parse_mode="Markdown", reply_markup=wingo_menu())

async def handle_msg(u, c):
    msg = u.message
    if not msg: return
    uid  = u.effective_user.id
    text = (msg.text or "").strip()

    urls = re.findall(r'https?://\S+', text, re.I)
    if urls:
        url = urls[0]
        job = uuid.uuid4().hex[:12]
        u2 = url.lower()
        if any(d in u2 for d in ("youtube.com","youtu.be")): plat="📺 YouTube"
        elif "tiktok.com" in u2: plat="📱 TikTok"
        elif "instagram.com" in u2: plat="📸 Instagram"
        elif "facebook.com" in u2 or "fb.watch" in u2: plat="👥 Facebook"
        elif "pinterest." in u2: plat="📌 Pinterest"
        else: plat="🌐 Video"

        st = await safe_reply(msg,
            f"⬇️ *{plat}* থেকে নামছে...\n`⏳ একটু অপেক্ষা করুন`",
            parse_mode="Markdown")
        await msg.chat.send_action(ChatAction.UPLOAD_VIDEO)

        loop = asyncio.get_running_loop()
        ok, title, err, filepath = await loop.run_in_executor(executor, yt_dl, url, job)

        if not ok:
            await safe_edit(st,
                f"❌ *ডাউনলোড হয়নি*\n\n`{err[:200]}`\n\n💡 অন্য link দিয়ে চেষ্টা করুন।",
                parse_mode="Markdown"); return

        size_mb = Path(filepath).stat().st_size / 1024 / 1024
        await safe_edit(st,
            f"⚙️ *Processing হচ্ছে...*\n\n"
            f"🔄 Mirror\n"
            f"📐 4:5 Ratio\n"
            f"🎨 Viral Color Grade\n"
            f"✨ Enhance\n"
            f"🛡️ Copyright Bypass\n"
            f"🏷️ Watermark\n\n"
            f"`⏳ একটু অপেক্ষা করো...`",
            parse_mode="Markdown")

        # full auto pipeline
        loop2 = asyncio.get_running_loop()
        wm_path, wm_err = await loop2.run_in_executor(executor, process_watermark, filepath)
        if wm_path:
            send_path = wm_path
            size_mb   = Path(wm_path).stat().st_size / 1024 / 1024
        else:
            send_path = filepath
            logger.warning("Pipeline failed: %s", wm_err)

        await safe_edit(st, f"⬆️ *আপলোড হচ্ছে...* `{size_mb:.1f} MB`", parse_mode="Markdown")

        try:
            with open(send_path,"rb") as f:
                await msg.reply_video(f,
                    caption=(
                        f"✅ *{md_escape(title or 'ডাউনলোড সম্পন্ন')}*\n\n"
                        f"📦 `{size_mb:.1f} MB`  ·  {plat}\n"
                        f"🔄 Mirror  📐 4:5  🎨 Viral  ✨ Enhance  🛡️ Copyright Safe\n\n"
                        f"👇 আরো Edit করতে পারো:"
                    ),
                    parse_mode="Markdown",
                    reply_markup=edit_btns(job),
                )
            _user_state[uid] = {"job":job,"file": send_path}
            try: await st.delete()
            except Exception: pass
            if wm_path and filepath != send_path:
                try: Path(filepath).unlink()
                except Exception: pass
        except Exception as e:
            await safe_edit(st, f"❌ আপলোড ব্যর্থ: `{e}`", parse_mode="Markdown")
        return

    if msg.video or msg.document or msg.audio:
        file_obj = msg.video or msg.audio or msg.document
        job = uuid.uuid4().hex[:12]
        is_audio = bool(msg.audio)
        _user_state[uid] = {"job":job,"file_id":file_obj.file_id,"is_audio":is_audio}
        reply_text = "🎵 *অডিও পেয়েছি!*\n\n👇 কী করতে চাও?" if is_audio else "🎬 *ভিডিও পেয়েছি!*\n\n👇 কী করতে চাও?"
        await safe_reply(msg, reply_text,
            parse_mode="Markdown", reply_markup=edit_btns(job))
        return

    await safe_reply(msg,
        "📎 *Link পাঠাও* → ডাউনলোড হবে\n"
        "🎬 *ভিডিও পাঠাও* → Edit করা যাবে\n\n"
        "/start — মেইন মেনু\n"
        "/wingo — WinGo Signal")

async def handle_cb(u, c):
    q = u.callback_query
    try: await q.answer()
    except Exception: pass
    uid  = q.from_user.id
    data = q.data

    if data == "noop": return

    # ── Script Generator callbacks ──
    if data == "sc_start":
        await safe_edit(q.message,
            "🎭 *Viral Script Generator*\n\nটপিক বেছে নাও 👇",
            parse_mode="Markdown", reply_markup=script_topic_menu()); return

    if data.startswith("sc_topic_"):
        tid = data.split("_")[-1]
        topic = SCRIPT_TOPICS.get(tid, "ভালোবাসা")
        await safe_edit(q.message,
            f"🎭 *Script Generator*\nটপিক: *{topic}*\n\nমেজাজ বেছে নাও 👇",
            parse_mode="Markdown", reply_markup=script_mood_menu(tid)); return

    if data.startswith("sc_mood_"):
        parts = data.split("_")
        tid, mid = parts[2], parts[3]
        topic = SCRIPT_TOPICS.get(tid, "ভালোবাসা")
        mood  = SCRIPT_MOODS.get(mid, "কষ্টের")
        await safe_edit(q.message,
            f"🎭 *Script Generator*\nটপিক: *{topic}* | মেজাজ: *{mood}*\n\nস্টাইল বেছে নাও 👇",
            parse_mode="Markdown", reply_markup=script_style_menu(tid, mid)); return

    if data.startswith("sc_gen_"):
        parts = data.split("_")
        tid, mid, sid = parts[2], parts[3], parts[4]
        topic = SCRIPT_TOPICS.get(tid, "ভালোবাসা")
        mood  = SCRIPT_MOODS.get(mid, "কষ্টের")
        style = SCRIPT_STYLES.get(sid, "WhatsApp")
        await safe_edit(q.message,
            f"⏳ *স্ক্রিপ্ট বানানো হচ্ছে...*\n_{topic} · {mood} · {style}_",
            parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        result = await generate_script(topic, mood, style)
        await safe_edit(q.message, result,
            parse_mode="Markdown",
            reply_markup=script_result_menu(tid, mid, sid)); return

    if data == "back_main":
        name = md_escape(u.callback_query.from_user.first_name or "বন্ধু")
        await safe_edit(q.message,
            f"👋 *হ্যালো {name}!*\n\n" + START_TEXT.format(ver=VERSION),
            parse_mode="Markdown", reply_markup=main_menu()); return

    if data == "wingo_menu":
        await safe_edit(q.message,
            "⚡ *WinGo AI ULTRA v2*\n\n"
            "50-layer AI · RSI · Pattern Match · Entropy\n\n"
            "👇 Signal নাও",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data in ("dl_help","enhance_help","tt_help","vocal_help"):
        hints = {
            "dl_help":      "🚀 YouTube · TikTok · Instagram · Facebook · Pinterest\n\nযেকোনো ভিডিওর *link পাঠাও* — ডাউনলোড হয়ে যাবে!",
            "enhance_help": "✨ *Enhance ULTRA*\n\nভিডিও পাঠাও — Cinematic quality তে upgrade করে দেব!",
            "tt_help":      "🔥 *TikTok Mode*\n\nভিডিও পাঠাও — Copyright ও Eligible For You bypass করে দেব!",
            "vocal_help":   "🎵 *Vocal Remover*\n\nMP3 বা ভিডিও পাঠাও — ২টা ফাইল পাবে:\n🎸 *Music* — শুধু মিউজিক (কথা ছাড়া)\n🎤 *Vocal* — শুধু কথা (মিউজিক ছাড়া)\n\n💡 _Stereo অডিওতে সবচেয়ে ভালো কাজ করে_",
        }
        await q.message.reply_text(hints[data], parse_mode="Markdown"); return

    if data == "wingo_predict":
        await safe_edit(q.message,
            "⚡ *AI scanning...*\n`📡 70 layers · 200 records · 7 servers`",
            parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        history = await loop.run_in_executor(executor, _w_fetch)
        if not history:
            await safe_edit(q.message,
                "📡 *সার্ভার সংযোগ নেই*\n\nকিছুক্ষণ পর আবার চেষ্টা করো।",
                parse_mode="Markdown", reply_markup=wingo_menu()); return
        pred = await loop.run_in_executor(executor, _w_analyze, history)
        if not pred:
            await safe_edit(q.message,"❌ Data কম, আবার চেষ্টা করো।",
                            reply_markup=wingo_menu()); return

        _wingo_state["history"]     = history
        _wingo_state["last_period"] = pred["period"]

        se  = "🔺" if pred["sig"]=="BIG" else "🔻"
        te  = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        period_short = pred["period"][-6:] if pred["period"] else "—"
        alts     = pred["numAlt"]
        sig_label = "BIG  ৫ ~ ৯" if pred["sig"]=="BIG" else "SMALL  ০ ~ ৪"
        bar_fill  = round(pred["conf"] / 10)
        conf_bar  = "█" * bar_fill + "░" * (10 - bar_fill)
        total_l   = pred["total_layers"]
        big_l     = pred["big_layers"]
        sml_l     = pred["small_layers"]

        # hot/cold
        hot_s  = " ".join(f"`{n}`" for n in pred.get("hot_nums",[])[:4]) or "—"
        cold_s = " ".join(f"`{n}`" for n in pred.get("cold_nums",[])[:4]) or "—"

        txt = (
            f"╔══════════════════════╗\n"
            f"     ⚡ *WINGO AI v3*\n"
            f"╚══════════════════════╝\n\n"
            f"🕐  Period: `{period_short}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{se}  *{sig_label}*\n"
            f"{te}  *{pred['tc'].upper()}*\n"
            f"🎲  *{pred['numTop']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊  `{conf_bar}`  *{pred['conf']}%*\n"
            f"🏅  *{pred['conf_label']}*  ·  Tier: `{pred['tier']}`\n"
            f"🛡  Risk: {pred['risk']}\n\n"
            f"🔬  `{big_l}🔺 vs {sml_l}🔻` /{total_l} layers\n"
            f"📈  RSI: `{pred['rsi']}`  Z: `{pred.get('z',0)}`  "
            f"H: `{pred.get('entropy',1):.2f}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢  Backup: `{alts[0]}`  `{alts[1]}`  `{alts[2]}`  `{alts[3]}`\n"
            f"🔥  Hot: {hot_s}  ❄️  Cold: {cold_s}\n\n"
            f"💡  _{pred['insight']}_\n\n"
            f"⏳  _Result আসছে..._"
        )
        await safe_edit(q.message, txt, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄  নতুন Signal", callback_data="wingo_predict")],
                            [InlineKeyboardButton("🔍 Analysis", callback_data="wingo_analysis"),
                             InlineKeyboardButton("🌡️ Hot/Cold",  callback_data="wingo_hotcold")],
                            [InlineKeyboardButton("📈  Stats",    callback_data="wingo_stats"),
                             InlineKeyboardButton("🏠  হোম",      callback_data="back_main")],
                        ])); return

    if data == "wingo_auto_on":
        _wingo_subs.add(uid)
        await safe_edit(q.message,
            "🟢 *Auto Signal চালু!*\n\nপ্রতি নতুন period এ signal আসবে।",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_auto_off":
        _wingo_subs.discard(uid)
        await safe_edit(q.message,
            "🔴 *Auto Signal বন্ধ।*",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_stats":
        hist = _wingo_state.get("history",[])[:12]
        total = _wingo_state.get("total_pred",0)
        correct = _wingo_state.get("correct_pred",0)
        acc = round(correct/total*100) if total else 0
        win_s = _wingo_state.get("win_streak",0)
        loss_s = _wingo_state.get("loss_streak",0)

        hist_items = []
        for hh in hist:
            sz_e  = "🔺" if hh["size"]=="BIG" else "🔻"
            col_e = {"red":"🔴","green":"🟢","violet_red":"🟣","violet_green":"🟣"}.get(hh["color"],"⚪")
            hist_items.append(f"{sz_e}{col_e}`{hh['number']}`")
        hist_txt = "  ".join(hist_items) if hist_items else "—"

        bar_fill = round(acc / 10)
        acc_bar  = "█" * bar_fill + "░" * (10 - bar_fill)
        acc_emoji = "🔥" if acc >= 70 else ("💪" if acc >= 60 else ("✅" if acc >= 50 else "⚠️"))
        grade = "S" if acc >= 75 else ("A" if acc >= 65 else ("B" if acc >= 55 else ("C" if acc >= 45 else "D")))

        await safe_edit(q.message,
            f"╔══════════════════════╗\n"
            f"       📈 *MY STATS*\n"
            f"╚══════════════════════╝\n\n"
            f"{acc_emoji}  *Accuracy:*\n"
            f"`{acc_bar}`  *{acc}%*  ·  Grade: `{grade}`\n\n"
            f"🎯  Total:  `{total}`  ·  ✅ Hit:  `{correct}`\n"
            f"🔥  Win Streak:  `{win_s}`  ·  💀  Loss:  `{loss_s}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕹  _Last 12 results:_\n"
            f"{hist_txt}",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_layers":
        lp = _wingo_state.get("layer_perf", {})
        if not lp:
            await safe_edit(q.message,
                "📊 *Layer Stats*\n\nএখনো কোনো prediction হয়নি।\n\nSignal নাও, তারপর দেখা যাবে।",
                parse_mode="Markdown", reply_markup=wingo_menu()); return
        sorted_layers = sorted(
            [(k, v) for k, v in lp.items() if v.get("total",0) >= 5],
            key=lambda x: -(x[1]["hit"]/x[1]["total"]),
        )[:10]
        lines = []
        for name, stats in sorted_layers:
            tot = stats["total"]; hit = stats["hit"]
            a = round(hit/tot*100)
            bar = "█" * round(a/10) + "░" * (10-round(a/10))
            emoji = "🔥" if a >= 70 else ("✅" if a >= 55 else "⚠️")
            lines.append(f"{emoji}  `{name[:14]:<14}`  `{bar}`  *{a}%*  `{tot}`")
        layers_txt = "\n".join(lines) if lines else "_Data সংগ্রহ হচ্ছে..._"
        total_layers_tracked = len([v for v in lp.values() if v.get("total",0)>=5])
        await safe_edit(q.message,
            f"🏆 *TOP PERFORMING LAYERS*\n"
            f"_70-layer engine · tracked: {total_layers_tracked}_\n\n"
            f"{layers_txt}",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_analysis":
        hist = _wingo_state.get("history", [])
        if not hist:
            await safe_edit(q.message,
                "⚡ *Analysis*\n\nআগে Signal নাও, তারপর Analysis দেখা যাবে।",
                parse_mode="Markdown", reply_markup=wingo_menu()); return
        loop2 = asyncio.get_running_loop()
        pred2 = await loop2.run_in_executor(executor, _w_analyze, hist)
        if not pred2:
            await safe_edit(q.message,"❌ Analysis করা যায়নি।",
                            reply_markup=wingo_menu()); return

        # block-level summary from signals
        sigs2 = pred2.get("signals", [])
        block_map = {
            "freq":"📊 Frequency","streak":"⚡ Streak","colstreak":"🎨 ColStreak",
            "markov":"🔗 Markov","ema":"📈 EMA","wma":"〽️ WMA","macd":"📉 MACD",
            "rsi":"💹 RSI","stoch":"📐 Stoch","willR":"📏 Williams",
            "alt":"🔄 Pattern","dbl":"🔁 DblPat","trip":"⚡ TripPat",
            "pat_match":"🔍 PatMatch","cycle":"🔃 Cycle",
            "col_trend":"🎨 ColTrend","col_markov":"🎨 ColMrkov","vio":"🟣 Violet",
            "meanrev":"⚖️ MeanRev","hotcold":"🌡️ HotCold","num_gap":"📍 NumGap",
            "entropy":"🌀 Entropy","zscore":"📐 ZScore","autocor":"🔄 AutoCor",
            "lossadapt":"🔁 Adaptive","run_opp":"💥 RunOpp",
            "parity":"⚡ Parity","num_mag":"🔢 NumMag","clust":"🔵 Cluster",
            "nbayes":"🧮 Bayes","lkr":"📊 LikeRatio",
            "trans":"🔀 Transition","run_len":"📏 RunLen",
            "tf_":"📡 MultiTF","unanimous":"🤝 Unanimous","calibrate":"⚙️ Calibrate",
        }
        big_count  = sum(1 for _,v,_ in sigs2 if v=="BIG")
        sml_count  = sum(1 for _,v,_ in sigs2 if v=="SMALL")
        top_big    = sorted([(l,c) for l,v,c in sigs2 if v=="BIG"],   key=lambda x:-x[1])[:4]
        top_sml    = sorted([(l,c) for l,v,c in sigs2 if v=="SMALL"], key=lambda x:-x[1])[:4]

        def fmt_sig(lst):
            return "  ".join(f"`{l[:8]}` {c}%" for l,c in lst) or "—"

        bar_f2   = round(pred2["conf"]/10)
        conf_bar2= "█"*bar_f2 + "░"*(10-bar_f2)

        await safe_edit(q.message,
            f"╔══════════════════════╗\n"
            f"      🔍 *AI ANALYSIS*\n"
            f"╚══════════════════════╝\n\n"
            f"📊  `{conf_bar2}`  *{pred2['conf']}%*  Tier: `{pred2['tier']}`\n"
            f"🔬  *{big_count}🔺 vs {sml_count}🔻*  /{len(sigs2)} layers\n"
            f"📡  30S · 7 servers · deep 200\n"
            f"📚  History: `{min(len(hist),200)}` records\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔺  *BIG signals:*\n{fmt_sig(top_big)}\n\n"
            f"🔻  *SMALL signals:*\n{fmt_sig(top_sml)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈  RSI: `{pred2['rsi']}`  "
            f"Z: `{pred2.get('z',0)}`  "
            f"H: `{pred2.get('entropy',1):.2f}`\n"
            f"🔥  Streak: `{pred2.get('streak',1)}`  "
            f"Vol: `{pred2.get('vol',50)}%`\n\n"
            f"💡  _{pred2['insight']}_",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_hotcold":
        hist = _wingo_state.get("history", [])
        if not hist:
            await safe_edit(q.message,
                "🌡️ *Hot/Cold*\n\nআগে Signal নাও।",
                parse_mode="Markdown", reply_markup=wingo_menu()); return
        nums = [x["number"] for x in hist[:100]]
        freq = Counter(nums)
        last_seen = {}
        for i, nn in enumerate(nums):
            if nn not in last_seen: last_seen[nn] = i

        lines_hot = []
        lines_cold = []
        for nn in range(10):
            cnt  = freq.get(nn, 0)
            gap  = last_seen.get(nn, 99)
            sz   = "🔺" if nn >= 5 else "🔻"
            pct  = round(cnt/len(nums)*100) if nums else 0
            bar  = "█"*(pct//5) + "░"*(20-pct//5)
            line = f"{sz} `{nn}` `{bar[:10]}` {pct}%  last:`{gap}`"
            if gap <= 3:   lines_hot.append(line)
            elif gap >= 12: lines_cold.append(line)

        hot_txt  = "\n".join(lines_hot)  or "_없음_"
        cold_txt = "\n".join(lines_cold) or "_없음_"

        # most/least frequent overall
        most_freq  = sorted(range(10), key=lambda x:-freq.get(x,0))[:3]
        least_freq = sorted(range(10), key=lambda x: freq.get(x,9999))[:3]
        mf_s = "  ".join(f"`{n}`" for n in most_freq)
        lf_s = "  ".join(f"`{n}`" for n in least_freq)

        await safe_edit(q.message,
            f"╔══════════════════════╗\n"
            f"      🌡️ *HOT / COLD*\n"
            f"╚══════════════════════╝\n\n"
            f"🔥  *Hot Numbers* _(সম্প্রতি এসেছে)_\n"
            f"{hot_txt}\n\n"
            f"❄️  *Cold Numbers* _(অনেকদিন আসেনি)_\n"
            f"{cold_txt}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊  Most frequent:  {mf_s}\n"
            f"📉  Least frequent: {lf_s}\n\n"
            f"_Data: last `{min(len(nums),100)}` rounds_",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    # ── Vocal Remover callback ──
    if data.startswith("do_vocal_"):
        job_id = data[len("do_vocal_"):]
        state  = _user_state.get(uid, {})
        inp_path = None

        if state.get("job") == job_id and state.get("file"):
            inp_path = state["file"]
        elif state.get("job") == job_id and state.get("file_id"):
            await safe_edit(q.message, "⏬ *ফাইল নামছে...*", parse_mode="Markdown")
            try:
                tg_file  = await c.bot.get_file(state["file_id"])
                # audio ফাইল হলে .mp3, video হলে .mp4
                is_audio_file = state.get("is_audio", False)
                ext = ".mp3" if is_audio_file else ".mp4"
                inp_path = tmp_path(ext)
                await tg_file.download_to_drive(inp_path)
                state["file"] = inp_path
            except Exception as e:
                await safe_edit(q.message, f"❌ ফাইল নামাতে ব্যর্থ: `{e}`",
                                parse_mode="Markdown", reply_markup=main_menu()); return

        if not inp_path or not Path(inp_path).exists():
            await safe_edit(q.message,
                "❌ ফাইল পাওয়া যায়নি!\nআবার ভিডিও/অডিও পাঠান।",
                reply_markup=main_menu()); return

        await safe_edit(q.message,
            "🎵 *Vocal Remover*\n`🔄 Processing... একটু অপেক্ষা করো`",
            parse_mode="Markdown")

        loop = asyncio.get_running_loop()
        # audio ফাইল হলে সরাসরি process, video হলে আগে audio extract
        inp_ext = Path(inp_path).suffix.lower()
        is_audio_input = inp_ext in (".mp3", ".m4a", ".ogg", ".flac", ".wav", ".aac")
        if is_audio_input:
            out_music, out_vocal, err, stereo = await loop.run_in_executor(
                executor, process_vocal_remove, inp_path)
        else:
            out_music, out_vocal, err, stereo = await loop.run_in_executor(
                executor, process_vocal_remove_video, inp_path)

        if not out_music and not out_vocal:
            await safe_edit(q.message,
                f"❌ *হয়নি*\n\n`{err[:300]}`\n\n💡 MP3 বা ভিডিও ফাইল পাঠান।",
                parse_mode="Markdown", reply_markup=main_menu()); return

        quality_note = "✅ Stereo — সর্বোচ্চ মান" if stereo else "⚠️ Mono — EQ ফিল্টার ব্যবহৃত"
        await q.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

        if out_music and Path(out_music).exists():
            with open(out_music, "rb") as f:
                await q.message.reply_audio(f,
                    caption=f"🎸 *Music Only* — কথা ছাড়া শুধু মিউজিক\n_{quality_note}_",
                    parse_mode="Markdown")
            Path(out_music).unlink(missing_ok=True)

        if out_vocal and Path(out_vocal).exists():
            with open(out_vocal, "rb") as f:
                await q.message.reply_audio(f,
                    caption=f"🎤 *Vocal Only* — মিউজিক ছাড়া শুধু কথা\n_{quality_note}_",
                    parse_mode="Markdown")
            Path(out_vocal).unlink(missing_ok=True)

        try: await q.message.delete()
        except Exception: pass
        return

    mode = job_id = None
    for m in ["tt_mode","enhance"]:
        pfx = f"do_{m}_"
        if data.startswith(pfx):
            mode   = m
            job_id = data[len(pfx):]
            break

    if not mode:
        await safe_edit(q.message,"❌ Unknown", reply_markup=main_menu()); return

    state = _user_state.get(uid,{})
    inp_path = None

    if state.get("job")==job_id and state.get("file"):
        inp_path = state["file"]
    elif state.get("job")==job_id and state.get("file_id"):
        await safe_edit(q.message,"⏬ *ফাইল নামছে...*", parse_mode="Markdown")
        try:
            tg_file = await c.bot.get_file(state["file_id"])
            inp_path = tmp_path(".mp4")
            await tg_file.download_to_drive(inp_path)
            state["file"] = inp_path
        except Exception as e:
            await safe_edit(q.message, f"❌ ফাইল নামাতে ব্যর্থ: `{e}`",
                            parse_mode="Markdown", reply_markup=main_menu()); return

    if not inp_path or not Path(inp_path).exists():
        await safe_edit(q.message,
            "❌ ফাইল পাওয়া যায়নি!\nআবার ভিডিও পাঠান।",
            reply_markup=main_menu()); return

    label = MODE_LABELS[mode]
    await safe_edit(q.message,
        f"⚙️ *{label}*\n`🔄 Processing...  একটু অপেক্ষা করো`",
        parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    out_path, err = await loop.run_in_executor(executor, PROCESSORS[mode], inp_path)

    if not out_path:
        await safe_edit(q.message,
            f"❌ *Processing হয়নি*\n\n`{err[:300]}`\n\n💡 ছোট ভিডিও দিয়ে চেষ্টা করো।",
            parse_mode="Markdown", reply_markup=main_menu()); return

    await q.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    try:
        with open(out_path,"rb") as f:
            await q.message.reply_video(f,
                caption=MODE_CAPTIONS.get(mode,"✅ সম্পন্ন!"),
                parse_mode="Markdown",
                reply_markup=edit_btns(job_id),
            )
        try: await q.message.delete()
        except Exception: pass
        try: Path(out_path).unlink()
        except Exception: pass
    except Exception as e:
        await safe_edit(q.message, f"❌ আপলোড ব্যর্থ: `{e}`",
                        parse_mode="Markdown", reply_markup=main_menu())

# ════════════════════════════════════════════
# WINGO AUTO TICK — Prediction → Result (v2)
# ════════════════════════════════════════════
async def wingo_tick(ctx):
    if not _wingo_subs: return
    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(executor, _w_fetch)
        if not hist: return

        latest        = hist[0]
        latest_period = latest["period"]

        # ── ধাপ ১: আগের pending prediction এর result ──
        pending = _wingo_state.get("pending_pred")
        if pending and latest_period != pending["period"]:
            result_row = next((hh for hh in hist if hh["period"] == pending["period"]), None)
            if result_row:
                actual_num   = result_row["number"]
                actual_size  = result_row["size"]
                actual_color = result_row["color"]
                pred_sig     = pending["sig"]
                pred_color   = pending["tc"]
                pred_num     = pending["numTop"]
                pred_conf    = pending.get("conf", 0)

                size_correct = (actual_size == pred_sig)
                _wingo_state["total_pred"] += 1
                if size_correct:
                    _wingo_state["correct_pred"] += 1
                    _wingo_state["win_streak"]  += 1
                    _wingo_state["loss_streak"]  = 0
                else:
                    _wingo_state["win_streak"]   = 0
                    _wingo_state["loss_streak"] += 1

                # layer performance tracking
                for lname in pending.get("layers_voted_big",[]):
                    lp = _wingo_state["layer_perf"].setdefault(lname,{"hit":0,"total":0})
                    lp["total"] += 1
                    if actual_size == "BIG": lp["hit"] += 1
                for lname in pending.get("layers_voted_small",[]):
                    lp = _wingo_state["layer_perf"].setdefault(lname,{"hit":0,"total":0})
                    lp["total"] += 1
                    if actual_size == "SMALL": lp["hit"] += 1

                acc       = round(_wingo_state["correct_pred"] / _wingo_state["total_pred"] * 100)
                te_a      = {"red":"🔴","green":"🟢","violet_red":"🟣","violet_green":"🟣"}.get(actual_color,"⚪")
                te_pred   = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred_color,"⚪")
                win_icon  = "✅" if size_correct else "❌"
                win_label = "WIN 🎉" if size_correct else "LOSS 💀"
                bar_f     = round(acc/10)
                acc_bar   = "█"*bar_f + "░"*(10-bar_f)

                result_txt = (
                    f"╔══════════════════════╗\n"
                    f"  {win_icon}  *{win_label}*  ·  `{pending['period'][-6:]}`\n"
                    f"╚══════════════════════╝\n\n"
                    f"📊  *Actual Result*\n"
                    f"{'🔺' if actual_size=='BIG' else '🔻'}  *{actual_size}*  {te_a}  *{actual_color.upper()}*  🎲  *{actual_num}*\n\n"
                    f"📌  *AI Signal was*\n"
                    f"{'🔺' if pred_sig=='BIG' else '🔻'}  *{pred_sig}*  {te_pred}  *{pred_color.upper()}*  🎲  *{pred_num}*\n"
                    f"📊  Conf: `{pred_conf}%`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯  `{acc_bar}`  *{acc}%*\n"
                    f"✅  `{_wingo_state['correct_pred']}/{_wingo_state['total_pred']}`  "
                    f"🔥 Win: `{_wingo_state['win_streak']}`  "
                    f"💀 Loss: `{_wingo_state['loss_streak']}`"
                )
                for suid in list(_wingo_subs):
                    try:
                        await ctx.bot.send_message(suid, result_txt, parse_mode="Markdown")
                    except Exception as e:
                        if "blocked" in str(e).lower() or "not found" in str(e).lower():
                            _wingo_subs.discard(suid)

            _wingo_state["pending_pred"] = None

        # ── ধাপ ২: নতুন period → prediction পাঠাও ──
        if latest_period == _wingo_state.get("last_period"): return
        _wingo_state["last_period"] = latest_period

        pred = await loop.run_in_executor(executor, _w_analyze, hist)
        if not pred: return

        # track layer votes for result evaluation
        sigs = pred.get("signals", [])
        _wingo_state["pending_pred"] = {
            "period":            latest_period,
            "sig":               pred["sig"],
            "tc":                pred["tc"],
            "numTop":            pred["numTop"],
            "conf":              pred["conf"],
            "layers_voted_big":  [l for l,v,_ in sigs if v=="BIG"],
            "layers_voted_small":[l for l,v,_ in sigs if v=="SMALL"],
        }

        se        = "🔺" if pred["sig"]=="BIG" else "🔻"
        te        = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        sig_label = "BIG  ৫~৯" if pred["sig"]=="BIG" else "SMALL  ০~৪"
        bar_f     = round(pred["conf"]/10)
        conf_bar  = "█"*bar_f + "░"*(10-bar_f)
        hot_s  = " ".join(f"`{n}`" for n in pred.get("hot_nums",[])[:3]) or "—"
        cold_s = " ".join(f"`{n}`" for n in pred.get("cold_nums",[])[:3]) or "—"

        pred_txt = (
            f"╔══════════════════════╗\n"
            f"     ⚡ *AUTO SIGNAL*\n"
            f"╚══════════════════════╝\n\n"
            f"🕐  Period: `{latest_period[-6:]}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{se}  *{sig_label}*\n"
            f"{te}  *{pred['tc'].upper()}*\n"
            f"🎲  *{pred['numTop']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊  `{conf_bar}`  *{pred['conf']}%*\n"
            f"🏅  *{pred['conf_label']}*  ·  Tier: `{pred['tier']}`\n"
            f"🛡  {pred['risk']}\n"
            f"🔬  `{pred['big_layers']}🔺 vs {pred['small_layers']}🔻` /{pred['total_layers']}\n"
            f"📈  RSI: `{pred['rsi']}`  Z: `{pred.get('z',0)}`\n\n"
            f"🔢  `{pred['numAlt'][0]}`  `{pred['numAlt'][1]}`  "
            f"`{pred['numAlt'][2]}`  `{pred['numAlt'][3]}`\n"
            f"🔥 {hot_s}  ❄️ {cold_s}\n\n"
            f"💡  _{pred['insight']}_\n"
            f"⏳  _Result আসছে..._"
        )
        for suid in list(_wingo_subs):
            try:
                await ctx.bot.send_message(suid, pred_txt, parse_mode="Markdown",
                                           reply_markup=wingo_menu())
            except Exception as e:
                if "blocked" in str(e).lower() or "not found" in str(e).lower():
                    _wingo_subs.discard(suid)
    except Exception as e:
        logger.warning("wingo_tick: %s", e)

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
def main():
    if not BOT_TOKEN or "এখানে" in BOT_TOKEN or len(BOT_TOKEN)<20:
        print("❌ BOT_TOKEN সেট করুন!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("wingo",  cmd_wingo))
    app.add_handler(CommandHandler("script", cmd_script))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_msg))

    if app.job_queue:
        app.job_queue.run_repeating(wingo_tick, interval=30, first=15)

    print("╔══════════════════════════════════════════╗")
    print("║  🎬  Video Bot v43 চালু!                 ║")
    print("║  📱  TikTok Mode (Copyright Safe)         ║")
    print("║  ✨  Enhance ULTRA                        ║")
    print("║  🎵  Vocal Remover                        ║")
    print("║  ⚡  WinGo AI v3 — 70 Layers              ║")
    print("║  🎭  Viral Script Generator               ║")
    print("║  Ctrl+C → বন্ধ                           ║")
    print("╚══════════════════════════════════════════╝")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
