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

BOT_TOKEN = os.getenv("BOT_TOKEN") or "এখানে_BOT_TOKEN_বসান"
ADMIN_ID  = int(os.getenv("ADMIN_ID") or "0")
VERSION   = "v42"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("vbot42")

CPU_COUNT = max(2, os.cpu_count() or 4)
executor  = ThreadPoolExecutor(max_workers=max(4, CPU_COUNT))
TEMP_DIR  = Path(tempfile.gettempdir()) / "vbot42"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════
# WINGO STATE
# ════════════════════════════════════════════
WINGO_APIS = [
    "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=50&ts=",
    "https://draw.ar-lottery02.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=50&ts=",
    "https://api.ar-lottery.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?pageSize=50&ts=",
]
_wingo_subs  = set()
_wingo_state = {
    "last_period": None,
    "history": [],
    "win_streak": 0,
    "loss_streak": 0,
    "total_pred": 0,
    "correct_pred": 0,
    "layer_perf": {},
    "pending_pred": None,   # {"period": ..., "sig": ..., "tc": ..., "numTop": ...}
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
            ["ffprobe","-v","error","-select_streams","a:0",
             "-show_entries","stream=codec_type","-of","csv=p=0",str(path)],
            capture_output=True, text=True, timeout=15)
        return "audio" in r.stdout
    except Exception:
        return True

def get_video_info(path):
    try:
        r = subprocess.run(
            ["ffprobe","-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height,duration",
             "-of","json",str(path)],
            capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        s = data.get("streams",[{}])[0]
        return {
            "width": int(s.get("width",1080)),
            "height": int(s.get("height",1920)),
            "duration": float(s.get("duration",0)),
        }
    except Exception:
        return {"width":1080,"height":1920,"duration":0}

def run_ffmpeg(cmd, timeout=300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out_file = cmd[-1]
        if Path(out_file).exists() and Path(out_file).stat().st_size > 1024:
            return True, ""
        stderr = r.stderr or ""
        all_lines = stderr.splitlines()
        # শুধু error keyword আছে এমন line খোঁজো — banner filtering বাদ
        err_keywords = ("error", "invalid", "failed", "no such", "unable",
                        "cannot", "could not", "denied", "not found",
                        "codec", "muxer", "permission", "option", "matches no",
                        "unrecognized", "unknown", "stream", "conversion")
        err_lines = [l for l in all_lines
                     if l.strip() and any(k in l.lower() for k in err_keywords)]
        if err_lines:
            err = "\n".join(err_lines[:5])
        elif all_lines:
            # শেষের ৫ লাইন — banner এর পর আসল error থাকে
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
            f"equalizer=f=10000:width_type=o:width=2:g=1.2,"
            f"equalizer=f=80:width_type=o:width=1:g=-0.8,"
            f"aecho=0.88:0.85:25:0.18,"
            f"loudnorm=I=-14:TP=-1:LRA=11"
        )
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","veryfast","-crf","21",
               "-c:a","aac","-b:a","192k",
               "-r","30",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
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

    scale_f = "scale=trunc(iw*1080/ih/2)*2:1080:flags=lanczos," if h < 1080 else ""

    vf = (
        f"hqdn3d=2:2:5:5,"
        f"{scale_f}"
        f"eq=contrast=1.08:brightness=0.02:saturation=1.20:gamma=0.97,"
        f"unsharp=3:3:1.0:3:3:0.3,"
        f"vignette=PI/5"
    )

    if has_audio(inp):
        af = "loudnorm=I=-16:TP=-1.5:LRA=11"
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","fast","-crf","18",
               "-c:a","aac","-b:a","192k",
               "-movflags","+faststart",out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","fast","-crf","18",
               "-movflags","+faststart",out]

    ok, err = run_ffmpeg(cmd)
    return (out if ok else None), err

PROCESSORS = {
    "tt_mode": process_tt_mode,
    "enhance": process_enhance,
}

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
# 🎯 WINGO ENGINE — 35 Layer
# ════════════════════════════════════════════
def _w_sizeof(n): return "BIG" if n >= 5 else "SMALL"
def _w_colorof(n):
    # আসল WinGo রুল: জোড়=red, বিজোড়=green, 0=violet_red, 5=violet_green
    if n == 0: return "violet_red"
    if n == 5: return "violet_green"
    return "red" if n % 2 == 0 else "green"

def _w_fetch():
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.ar-lottery01.com/",
    }
    for api in WINGO_APIS:
        try:
            url = api + str(int(time.time() * 1000))
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("utf-8", errors="ignore")
                data = json.loads(raw)

            # আসল structure: data.data.list
            rows = []
            if isinstance(data, dict):
                inner = data.get("data", {})
                if isinstance(inner, dict):
                    rows = inner.get("list", [])
                elif isinstance(inner, list):
                    rows = inner

            out = []
            for row in rows[:50]:
                try:
                    n = int(row.get("number") or row.get("num") or row.get("winNumber") or -1)
                    p = str(row.get("issueNumber") or row.get("period") or row.get("issue") or "")
                    if n < 0 or not p: continue

                    # color field: "green,violet" বা "red" বা "green" ইত্যাদি
                    raw_color = str(row.get("color") or "").lower().strip()
                    if "violet" in raw_color and "green" in raw_color:
                        color = "violet_green"   # 5 → green + violet
                    elif "violet" in raw_color and "red" in raw_color:
                        color = "violet_red"     # 0 → red + violet
                    elif "violet" in raw_color:
                        color = "violet_red" if n == 0 else "violet_green"
                    elif raw_color in ("red", "green"):
                        color = raw_color
                    else:
                        color = _w_colorof(n)   # fallback

                    out.append({"period": p, "number": n, "size": _w_sizeof(n), "color": color})
                except Exception:
                    continue

            if out:
                logger.info("WinGo: %d records from %s", len(out), api)
                return out
        except Exception as e:
            logger.warning("wingo fetch failed [%s]: %s", api, e)
    return []

def _w_analyze(history):
    if len(history) < 5: return None
    N   = min(len(history), 50)
    h   = history[:N]
    nums   = [x["number"] for x in h]
    sizes  = [x["size"]   for x in h]
    colors = [x["color"]  for x in h]

    sb = ss = 0.0
    signals = []   # (label, vote, confidence 0-1)

    def vote(label, big_w, small_w, base=1.0):
        nonlocal sb, ss
        # adaptive weight từ lịch sử layer
        lp  = _wingo_state["layer_perf"].get(label, {})
        tot = lp.get("total", 0)
        if tot >= 20:
            acc = lp["hit"] / tot
            mul = 1.6 if acc > 0.63 else (0.4 if acc < 0.40 else 1.0)
            base = base * mul
        sb += big_w * base
        ss += small_w * base
        total = big_w + small_w or 1
        conf  = max(big_w, small_w) / total
        winner = "BIG" if big_w >= small_w else "SMALL"
        signals.append((label, winner, round(conf * 100)))

    # ── 1. SHORT-TERM FREQUENCY (last 5) ──────────────────
    b5 = sizes[:5].count("BIG")
    if b5 >= 4:   vote("freq5",   0, 2.0, 1.6)   # 4-5 BIG → SMALL কমিং
    elif b5 <= 1: vote("freq5",   2.0, 0, 1.6)
    else:         vote("freq5",   b5/5, (5-b5)/5, 0.6)

    # ── 2. MID-TERM FREQUENCY (last 10) ───────────────────
    b10 = sizes[:10].count("BIG")
    if b10 >= 8:   vote("freq10",  0, 1.5, 1.3)
    elif b10 <= 2: vote("freq10",  1.5, 0, 1.3)
    else:          vote("freq10",  b10/10, (10-b10)/10, 0.7)

    # ── 3. LONG-TERM FREQUENCY (last 30) ──────────────────
    b30 = sizes[:min(30,N)].count("BIG")
    n30 = min(30, N)
    vote("freq30", b30/n30, (n30-b30)/n30, 0.8)

    # ── 4. STREAK — MEAN REVERSION ────────────────────────
    streak = 1
    for i in range(1, min(N, 20)):
        if sizes[i] == sizes[0]: streak += 1
        else: break
    opp_b = 1 if sizes[0] == "SMALL" else 0
    opp_s = 1 if sizes[0] == "BIG"   else 0
    if   streak >= 7: vote("streak", opp_b*3.0, opp_s*3.0, 2.0)
    elif streak >= 5: vote("streak", opp_b*2.2, opp_s*2.2, 1.8)
    elif streak >= 3: vote("streak", opp_b*1.5, opp_s*1.5, 1.4)
    elif streak >= 2: vote("streak", opp_b*1.1, opp_s*1.1, 1.0)
    else:             vote("streak", 0.5, 0.5, 0.4)

    # ── 5. MARKOV ORDER-1 ─────────────────────────────────
    if N >= 4:
        m1 = {}
        for i in range(N - 1):
            k = sizes[i+1]; m1.setdefault(k, {"BIG":0,"SMALL":0})
            m1[k][sizes[i]] += 1
        c = m1.get(sizes[0], {"BIG":0,"SMALL":0})
        t = c["BIG"] + c["SMALL"]
        if t >= 6: vote("markov1", c["BIG"]/t, c["SMALL"]/t, 1.4)
        elif t>=3: vote("markov1", c["BIG"]/t, c["SMALL"]/t, 1.0)

    # ── 6. MARKOV ORDER-2 ─────────────────────────────────
    if N >= 5:
        m2 = {}
        for i in range(N - 2):
            k = sizes[i+2]+"|"+sizes[i+1]; m2.setdefault(k, {"BIG":0,"SMALL":0})
            m2[k][sizes[i]] += 1
        k2 = sizes[0]+"|"+sizes[1]
        c  = m2.get(k2, {"BIG":0,"SMALL":0})
        t  = c["BIG"] + c["SMALL"]
        if t >= 5: vote("markov2", c["BIG"]/t, c["SMALL"]/t, 1.6)
        elif t>=3: vote("markov2", c["BIG"]/t, c["SMALL"]/t, 1.1)

    # ── 7. MARKOV ORDER-3 ─────────────────────────────────
    if N >= 6:
        m3 = {}
        for i in range(N - 3):
            k = sizes[i+3]+"|"+sizes[i+2]+"|"+sizes[i+1]
            m3.setdefault(k, {"BIG":0,"SMALL":0})
            m3[k][sizes[i]] += 1
        k3 = sizes[0]+"|"+sizes[1]+"|"+sizes[2]
        c  = m3.get(k3, {"BIG":0,"SMALL":0})
        t  = c["BIG"] + c["SMALL"]
        if t >= 4: vote("markov3", c["BIG"]/t, c["SMALL"]/t, 1.8)
        elif t>=2: vote("markov3", c["BIG"]/t, c["SMALL"]/t, 1.2)

    # ── 8. EMA SHORT (α=0.25, 10 rounds) ─────────────────
    ema_s = 1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1, min(N, 10)):
        ema_s = 0.25*(1 if sizes[i]=="BIG" else 0) + 0.75*ema_s
    vote("ema_short", 1-ema_s, ema_s, 1.2)

    # ── 9. EMA LONG (α=0.10, 30 rounds) ──────────────────
    ema_l = 1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1, min(N, 30)):
        ema_l = 0.10*(1 if sizes[i]=="BIG" else 0) + 0.90*ema_l
    vote("ema_long", 1-ema_l, ema_l, 0.9)

    # ── 10. MOMENTUM (short EMA vs long EMA) ──────────────
    diff = ema_s - ema_l
    if   diff >  0.20: vote("momentum", 0, 1.5, 1.1)   # BIG momentum → might exhaust
    elif diff < -0.20: vote("momentum", 1.5, 0, 1.1)
    else:              vote("momentum", 0.5, 0.5, 0.4)

    # ── 11. HOT/COLD NUMBERS ──────────────────────────────
    last_seen = {}
    for i, n in enumerate(nums):
        if n not in last_seen: last_seen[n] = i
    cold_big   = [n for n in range(5,10) if last_seen.get(n, N+5) >= 10]
    cold_small = [n for n in range(0,5)  if last_seen.get(n, N+5) >= 10]
    if len(cold_big)   >= 2: vote("hotcold", 0, 1.4, 1.0)
    elif len(cold_small)>=2: vote("hotcold", 1.4, 0, 1.0)
    else:                    vote("hotcold", 0.5, 0.5, 0.3)

    # ── 12. NUMBER GAP (due numbers) ──────────────────────
    gaps = {n: (next((i for i,x in enumerate(nums) if x==n), N+5)) for n in range(10)}
    due_big   = sum(1 for n in range(5,10) if gaps[n] >= 8)
    due_small = sum(1 for n in range(0,5)  if gaps[n] >= 8)
    if   due_big   >= 3: vote("gap", 0, 1.3, 0.9)
    elif due_small >= 3: vote("gap", 1.3, 0, 0.9)
    else:                vote("gap", 0.5, 0.5, 0.3)

    # ── 13. VOLATILITY ────────────────────────────────────
    if N >= 8:
        alt = sum(1 for i in range(1, min(N,10)) if sizes[i] != sizes[i-1])
        vol = alt / 9
        if vol >= 0.85:   vote("volatility", 0.5, 0.5, 0.2)   # chaotic → neutral
        elif vol <= 0.30: vote("volatility",   # trending
            1.2 if sizes[0]=="BIG" else 0, 1.2 if sizes[0]=="SMALL" else 0, 1.0)
        else:             vote("volatility", 0.5, 0.5, 0.4)

    # ── 14. ALTERNATION PATTERN ───────────────────────────
    if N >= 6:
        alt6 = sum(1 for i in range(1, 6) if sizes[i] != sizes[i-1])
        if alt6 >= 5:   # strict alternating → follow pattern
            nxt = "SMALL" if sizes[0]=="BIG" else "BIG"
            vote("alternation", 1.5 if nxt=="BIG" else 0, 1.5 if nxt=="SMALL" else 0, 1.3)
        else:           vote("alternation", 0.5, 0.5, 0.3)

    # ── 15. COLOR TREND → SIZE ────────────────────────────
    red_recent   = sum(1 for c in colors[:8] if c in ("red","violet_red"))
    green_recent = sum(1 for c in colors[:8] if c in ("green","violet_green"))
    if   red_recent   >= 6: vote("color_trend", 1.2, 0,   0.9)  # RED→BIG
    elif green_recent >= 6: vote("color_trend", 0,   1.2, 0.9)  # GREEN→SMALL
    else:                   vote("color_trend", 0.5, 0.5, 0.3)

    # ── 16. COLOR MARKOV ──────────────────────────────────
    if N >= 4:
        cm = {}
        for i in range(N - 1):
            k = colors[i+1]; cm.setdefault(k, {"BIG":0,"SMALL":0})
            cm[k][sizes[i]] += 1
        c = cm.get(colors[0], {"BIG":0,"SMALL":0})
        t = c["BIG"] + c["SMALL"]
        if t >= 6: vote("colormarkov", c["BIG"]/t, c["SMALL"]/t, 1.2)
        elif t>=3: vote("colormarkov", c["BIG"]/t, c["SMALL"]/t, 0.8)

    # ── 17. MEAN REVERSION (sum deviation) ────────────────
    if N >= 10:
        expected_big = N / 2
        actual_big   = sizes[:N].count("BIG")
        dev = actual_big - expected_big
        if   dev >= 8:  vote("meanrev",  0, 2.0, 1.4)
        elif dev >= 5:  vote("meanrev",  0, 1.3, 1.1)
        elif dev <= -8: vote("meanrev",  2.0, 0, 1.4)
        elif dev <= -5: vote("meanrev",  1.3, 0, 1.1)
        else:           vote("meanrev",  0.5, 0.5, 0.4)

    # ── 18. CONSECUTIVE SAME COLOR ────────────────────────
    col_streak = 1
    for i in range(1, min(N, 10)):
        if colors[i] == colors[0]: col_streak += 1
        else: break
    if col_streak >= 5:
        # long color streak → next color might flip → opposite size
        opp = "BIG" if colors[0] in ("green","violet_green") else "SMALL"
        vote("colstreak", 1.6 if opp=="BIG" else 0, 1.6 if opp=="SMALL" else 0, 1.2)
    else: vote("colstreak", 0.5, 0.5, 0.3)

    # ── 19. LOSS STREAK ADAPTATION ────────────────────────
    loss_stk = _wingo_state.get("loss_streak", 0)
    win_stk  = _wingo_state.get("win_streak",  0)
    if loss_stk >= 3:
        # flip — go against current leaning
        vote("lossadapt", ss*0.8, sb*0.8, 1.5)
    elif win_stk >= 5:
        vote("winadapt",  sb*0.4, ss*0.4, 0.5)
    else:
        vote("streak_neut", 0.5, 0.5, 0.2)

    # ── 20. SELF-ACCURACY FEEDBACK ────────────────────────
    total   = _wingo_state.get("total_pred", 0)
    correct = _wingo_state.get("correct_pred", 0)
    if total >= 10:
        acc = correct / total
        if acc < 0.38: vote("acc_flip", ss, sb, 0.9)
        elif acc > 0.68: vote("acc_keep", sb, ss, 0.5)

    # ═══════════════════════════════════════════════
    # FINAL SIZE SIGNAL
    # ═══════════════════════════════════════════════
    tw  = sb + ss or 1
    pB  = round(sb / tw * 100)
    pS  = 100 - pB
    sig = "BIG" if sb >= ss else "SMALL"
    # confidence = agreement level across top signals
    conf = max(pB, pS)

    # ═══════════════════════════════════════════════
    # COLOR PREDICTION (multi-factor)
    # ═══════════════════════════════════════════════
    cs = {"red": 0.0, "green": 0.0, "violet": 0.0}
    for i, col in enumerate(colors[:30]):
        w = 1.0 / (i * 0.07 + 1)
        if   col in ("red",    "violet_red"):   cs["red"]   += w
        elif col in ("green",  "violet_green"): cs["green"] += w
        else:                                   cs["violet"] += w * 1.5
    # size→color bias (even=red, odd=green)
    if sig == "BIG":   cs["red"]   += 3.5; cs["violet"] += 0.8
    else:              cs["green"] += 3.5; cs["violet"] += 0.8
    # color gap bonus
    last_vio = next((i for i,c in enumerate(colors) if "violet" in c), 99)
    if last_vio >= 12: cs["violet"] += 2.5   # violet due
    ct = sum(cs.values()) or 1
    pR = round(cs["red"]   / ct * 100)
    pG = round(cs["green"] / ct * 100)
    pV = max(0, 100 - pR - pG)
    tc = "red" if pR>=pG and pR>=pV else ("green" if pG>=pR and pG>=pV else "violet")

    # ═══════════════════════════════════════════════
    # NUMBER PREDICTION (gap + size + hot scoring)
    # ═══════════════════════════════════════════════
    ns = [0.0] * 10
    for i, n in enumerate(nums[:40]):
        ns[n] += 1.0 / (i * 0.06 + 1)
    # boost numbers matching predicted size
    for n in range(10):
        if _w_sizeof(n) == sig: ns[n] += 5.0
    # boost cold numbers (due)
    for n in range(10):
        gap = gaps.get(n, N)
        if gap >= 8: ns[n] += gap * 0.25
    ranked = sorted(range(10), key=lambda x: -ns[x])

    # ═══════════════════════════════════════════════
    # MARKET INSIGHT (1 line summary)
    # ═══════════════════════════════════════════════
    insight = ""
    if streak >= 5:
        insight = f"{'🔺' if sizes[0]=='BIG' else '🔻'} {streak}x Streak → Reversal likely"
    elif loss_stk >= 3:
        insight = f"❗ {loss_stk}x Loss → Strategy flipped"
    elif conf >= 80:
        insight = "🔥 High agreement across layers"
    elif vol if N >= 8 else False:
        pass
    if not insight:
        dom = "BIG" if b10 >= 7 else ("SMALL" if b10 <= 3 else None)
        if dom:
            insight = f"📊 {dom} dominant last 10 → Rebalancing"
        else:
            insight = "📊 Market balanced — pattern-based call"

    if   conf >= 80: conf_label = "🔥 ULTRA"
    elif conf >= 70: conf_label = "💪 HIGH"
    elif conf >= 60: conf_label = "✅ MID"
    else:            conf_label = "⚠️ LOW"

    big_layers   = sum(1 for _, v, _ in signals if v=="BIG")
    small_layers = sum(1 for _, v, _ in signals if v=="SMALL")

    return {
        "sig": sig, "conf": conf, "conf_label": conf_label,
        "pB": pB, "pS": pS, "pR": pR, "pG": pG, "pV": pV, "tc": tc,
        "numTop": ranked[0], "numAlt": ranked[1:5],
        "period": history[0]["period"] if history else "",
        "big_layers": big_layers, "small_layers": small_layers,
        "total_layers": len(signals),
        "insight": insight, "streak": streak,
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
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("⚡  WinGo AI Signal", callback_data="wingo_menu")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
    ])

def wingo_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯  Signal নাও এখনই!", callback_data="wingo_predict")],
        [InlineKeyboardButton("🟢  Auto চালু", callback_data="wingo_auto_on"),
         InlineKeyboardButton("🔴  Auto বন্ধ", callback_data="wingo_auto_off")],
        [InlineKeyboardButton("📈  আমার Stats", callback_data="wingo_stats"),
         InlineKeyboardButton("🏠  হোম", callback_data="back_main")],
    ])

def edit_btns(job):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥  TikTok Mode", callback_data=f"do_tt_mode_{job}"),
         InlineKeyboardButton("✨  Enhance", callback_data=f"do_enhance_{job}")],
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
│  ⚡  *WinGo AI Signal*
│  35-layer pattern engine
└─────────────────────────┘

📎 _Link পাঠান_ → Download
🎬 _ভিডিও পাঠান_ → Edit
""".strip()

# ════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════
async def cmd_start(u, c):
    name = md_escape(u.effective_user.first_name or "বন্ধু")
    await safe_reply(u.message,
        f"👋 *হ্যালো {name}!*\n\n" + START_TEXT.format(ver=VERSION),
        parse_mode="Markdown", reply_markup=main_menu())

async def cmd_wingo(u, c):
    await safe_reply(u.message,
        "⚡ *WinGo AI Signal*\n\n"
        "35-layer pattern engine চালু আছে\n"
        "👇 নিচে থেকে Signal নাও",
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
        await safe_edit(st, f"⬆️ *আপলোড হচ্ছে...* `{size_mb:.1f} MB`", parse_mode="Markdown")

        try:
            with open(filepath,"rb") as f:
                await msg.reply_video(f,
                    caption=(
                        f"✅ *{md_escape(title or 'ডাউনলোড সম্পন্ন')}*\n\n"
                        f"📦 `{size_mb:.1f} MB`  ·  {plat}\n\n"
                        f"👇 এখন Edit করতে পারো:"
                    ),
                    parse_mode="Markdown",
                    reply_markup=edit_btns(job),
                )
            _user_state[uid] = {"job":job,"file":filepath}
            try: await st.delete()
            except Exception: pass
        except Exception as e:
            await safe_edit(st, f"❌ আপলোড ব্যর্থ: `{e}`", parse_mode="Markdown")
        return

    if msg.video or msg.document:
        file_obj = msg.video or msg.document
        job = uuid.uuid4().hex[:12]
        _user_state[uid] = {"job":job,"file_id":file_obj.file_id}
        await safe_reply(msg,
            "🎬 *ভিডিও পেয়েছি!*\n\n👇 কী করতে চাও?",
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

    if data == "back_main":
        name = md_escape(u.callback_query.from_user.first_name or "বন্ধু")
        await safe_edit(q.message,
            f"👋 *হ্যালো {name}!*\n\n" + START_TEXT.format(ver=VERSION),
            parse_mode="Markdown", reply_markup=main_menu()); return

    if data == "wingo_menu":
        await safe_edit(q.message,
            "⚡ *WinGo AI Signal*\n\n"
            "35-layer pattern engine চালু আছে\n"
            "👇 নিচে থেকে Signal নাও",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data in ("dl_help","enhance_help","tt_help"):
        hints = {
            "dl_help":      "🚀 YouTube · TikTok · Instagram · Facebook · Pinterest\n\nযেকোনো ভিডিওর *link পাঠাও* — ডাউনলোড হয়ে যাবে!",
            "enhance_help": "✨ *Enhance ULTRA*\n\nভিডিও পাঠাও — Cinematic quality তে upgrade করে দেব!",
            "tt_help":      "🔥 *TikTok Mode*\n\nভিডিও পাঠাও — Copyright ও Eligible For You bypass করে দেব!",
        }
        await q.message.reply_text(hints[data], parse_mode="Markdown"); return

    if data == "wingo_predict":
        await safe_edit(q.message,
            "⚡ *Signal তৈরি হচ্ছে...*\n`35 layers scanning`",
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
        alts = pred["numAlt"]
        sig_label = "BIG  ৫ ~ ৯" if pred["sig"]=="BIG" else "SMALL  ০ ~ ৪"

        txt = (
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"        ⚡ *AI SIGNAL*\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"🕐  Period  `{period_short}`\n\n"
            f"{'━'*22}\n"
            f"{se}  *{sig_label}*\n"
            f"{te}  *{pred['tc'].upper()}*\n"
            f"🎲  *{pred['numTop']}*\n"
            f"{'━'*22}\n\n"
            f"🔢  _Backup:_  `{alts[0]}`  `{alts[1]}`  `{alts[2]}`  `{alts[3]}`\n\n"
            f"⏳  _Result আসছে..._"
        )
        await safe_edit(q.message, txt, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄  নতুন Signal", callback_data="wingo_predict")],
                            [InlineKeyboardButton("📈  Stats", callback_data="wingo_stats"),
                             InlineKeyboardButton("🏠  হোম", callback_data="back_main")],
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
        hist = _wingo_state.get("history",[])[:10]
        total = _wingo_state.get("total_pred",0)
        correct = _wingo_state.get("correct_pred",0)
        acc = round(correct/total*100) if total else 0
        win_s = _wingo_state.get("win_streak",0)
        loss_s = _wingo_state.get("loss_streak",0)
        hist_items = []
        for h in hist:
            sz_e = "🔺" if h["size"]=="BIG" else "🔻"
            col_e = {"red":"🔴","green":"🟢","violet_red":"🟣","violet_green":"🟣"}.get(h["color"],"⚪")
            hist_items.append(f"{sz_e}{col_e}`{h['number']}`")
        hist_txt = "  ".join(hist_items) if hist_items else "—"

        acc_bar_filled = round(acc / 10)
        acc_bar = "█" * acc_bar_filled + "░" * (10 - acc_bar_filled)
        acc_emoji = "🔥" if acc >= 70 else ("✅" if acc >= 55 else "⚠️")

        await safe_edit(q.message,
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"        📈 *MY STATS*\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"{acc_emoji}  Accuracy:  `{acc_bar}`  *{acc}%*\n"
            f"🎯  Total:  `{total}`  ·  ✅ Hit:  `{correct}`\n\n"
            f"🔥  Win Streak:  `{win_s}`\n"
            f"💀  Loss Streak:  `{loss_s}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕹  _Last 10 results:_\n"
            f"{hist_txt}",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

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
# WINGO AUTO TICK — Prediction → Result
# ════════════════════════════════════════════
async def wingo_tick(ctx):
    if not _wingo_subs: return
    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(executor, _w_fetch)
        if not hist: return

        latest = hist[0]
        latest_period = latest["period"]

        # ── ধাপ ১: আগের pending prediction এর result দেখাও ──
        pending = _wingo_state.get("pending_pred")
        if pending and latest_period != pending["period"]:
            # আগের period এর result এসে গেছে
            result_row = next((h for h in hist if h["period"] == pending["period"]), None)
            if result_row:
                actual_num    = result_row["number"]
                actual_size   = result_row["size"]
                actual_color  = result_row["color"]
                pred_sig      = pending["sig"]
                pred_color    = pending["tc"]
                pred_num      = pending["numTop"]

                size_correct  = (actual_size == pred_sig)
                color_correct = (actual_color == pred_color)

                _wingo_state["total_pred"] += 1
                if size_correct:
                    _wingo_state["correct_pred"] += 1
                    _wingo_state["win_streak"]  += 1
                    _wingo_state["loss_streak"]  = 0
                    result_emoji = "✅ WIN"
                else:
                    _wingo_state["win_streak"]   = 0
                    _wingo_state["loss_streak"] += 1

                acc = round(_wingo_state["correct_pred"] / _wingo_state["total_pred"] * 100)
                te_a = {"red":"🔴","green":"🟢","violet":"🟣"}.get(actual_color,"⚪")
                win_icon  = "✅" if size_correct else "❌"
                win_label = "WIN" if size_correct else "LOSS"

                te_pred = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred_color,"⚪")
                result_txt = (
                    f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"  {win_icon}  *{win_label}*  ·  `{pending['period'][-6:]}`\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
                    f"📊  *Result*\n"
                    f"{'🔺' if actual_size=='BIG' else '🔻'}  *{actual_size}*  {te_a}  *{actual_color.upper()}*  🎲  *{actual_num}*\n\n"
                    f"📌  *Signal ছিল*\n"
                    f"{'🔺' if pred_sig=='BIG' else '🔻'}  *{pred_sig}*  {te_pred}  *{pred_color.upper()}*  🎲  *{pred_num}*\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯  `{acc}%`  ·  `{_wingo_state['correct_pred']}/{_wingo_state['total_pred']}`"
                )
                for uid in list(_wingo_subs):
                    try:
                        await ctx.bot.send_message(uid, result_txt, parse_mode="Markdown")
                    except Exception as e:
                        if "blocked" in str(e).lower() or "not found" in str(e).lower():
                            _wingo_subs.discard(uid)

            _wingo_state["pending_pred"] = None

        # ── ধাপ ২: নতুন period এর জন্য prediction পাঠাও ──
        if latest_period == _wingo_state.get("last_period"): return
        _wingo_state["last_period"] = latest_period

        pred = await loop.run_in_executor(executor, _w_analyze, hist)
        if not pred: return

        # pending এ রাখো পরের result এর জন্য
        _wingo_state["pending_pred"] = {
            "period": latest_period,
            "sig":    pred["sig"],
            "tc":     pred["tc"],
            "numTop": pred["numTop"],
        }

        se  = "🔺" if pred["sig"]=="BIG" else "🔻"
        te  = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        sig_label = "BIG  ৫ ~ ৯" if pred["sig"]=="BIG" else "SMALL  ০ ~ ৪"

        pred_txt = (
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"        ⚡ *AI SIGNAL*\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
            f"🕐  Period  `{latest_period[-6:]}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{se}  *{sig_label}*\n"
            f"{te}  *{pred['tc'].upper()}*\n"
            f"🎲  *{pred['numTop']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢  _Backup:_  `{pred['numAlt'][0]}`  `{pred['numAlt'][1]}`  `{pred['numAlt'][2]}`  `{pred['numAlt'][3]}`\n\n"
            f"⏳  _Result আসছে..._"
        )
        for uid in list(_wingo_subs):
            try:
                await ctx.bot.send_message(uid, pred_txt, parse_mode="Markdown",
                                           reply_markup=wingo_menu())
            except Exception as e:
                if "blocked" in str(e).lower() or "not found" in str(e).lower():
                    _wingo_subs.discard(uid)
    except Exception as e:
        logger.warning("wingo_tick: %s", e)

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
def main():
    if not BOT_TOKEN or "এখানে" in BOT_TOKEN or len(BOT_TOKEN)<20:
        print("❌ BOT_TOKEN সেট করুন!")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("wingo", cmd_wingo))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_msg))
    app.job_queue.run_repeating(wingo_tick, interval=30, first=15)

    print("╔══════════════════════════════════════════╗")
    print("║  🎬  Video Bot v42 চালু!                 ║")
    print("║  📱  TikTok Mode (Copyright Safe)         ║")
    print("║  ✨  Enhance ULTRA                        ║")
    print("║  🎯  WinGo ULTRA — 35 Layers              ║")
    print("║  Ctrl+C → বন্ধ                           ║")
    print("╚══════════════════════════════════════════╝")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
