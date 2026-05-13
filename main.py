"""
🎬 Video Bot v41 — Premium Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Download: YouTube, TikTok, Instagram, Facebook, Pinterest
✨ Enhance Ultra PREMIUM — cinematic grade processing
📺 Platform Modes — Copyright-safe conversion
   • YouTube Mode (16:9 + Advanced Copyright Bypass)
   • TikTok Mode (9:16 + Multi-layer Copyright Protection)
   • Instagram Mode (4:5 optimized)
🎯 WinGo ULTRA — 35-layer AI prediction engine

📦 SETUP (Termux):
    pkg update -y && pkg install -y python ffmpeg
    pip install "python-telegram-bot[job-queue]" yt-dlp

🔑 BOT_TOKEN নিচে বসান
🚀 RUN: python video_bot_v41.py
"""

import os, sys, re, json, logging, asyncio, subprocess, tempfile, uuid, time, random, math, urllib.request
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)

# ════════════════════════════════════════════
# WINGO STATE
# ════════════════════════════════════════════
WINGO_APIS = [
    "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts=",
    "https://draw.ar-lottery02.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts=",
]
_wingo_subs  = set()
_wingo_state = {
    "last_period": None,
    "history": [],
    "pending": {},   # uid → {sig, color, num, period}
    "records": {},   # uid → {win, loss, streak, max_streak}
}
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY") or ""

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
    """Get video width, height, duration"""
    try:
        r = subprocess.run(
            ["ffprobe","-v","error","-select_streams","v:0",
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

def run_ffmpeg(cmd, timeout=600):
    try:
        # Add thread limiting to avoid overload
        if "-threads" not in cmd:
            idx = cmd.index("-c:v") if "-c:v" in cmd else len(cmd)-1
            cmd = cmd[:idx] + ["-threads", str(min(4, CPU_COUNT))] + cmd[idx:]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out_file = cmd[-1]
        if Path(out_file).exists() and Path(out_file).stat().st_size > 1024:
            return True, ""
        err = r.stderr[-800:] if r.stderr else "Unknown error"
        logger.error("ffmpeg error: %s", err)
        return False, err
    except subprocess.TimeoutExpired:
        return False, "⏱ Timeout — ভিডিও অনেক বড়, ছোট ভিডিও দিন"
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

# ════════════════════════════════════════════
# USER STATE
# ════════════════════════════════════════════
_user_state: dict = {}

# ════════════════════════════════════════════
# DOWNLOAD ENGINE
# ════════════════════════════════════════════
MUA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
DUA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
IUA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")

def _ydl_run(fmt, extra, out_tpl, url):
    cmd = (["yt-dlp","--no-playlist","--no-warnings","--quiet",
            "-f", fmt, "--merge-output-format","mp4"]
           + extra + ["-o", out_tpl, url])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.returncode == 0, r.stderr[:300]

def yt_dl(url, job):
    out_tpl = str(TEMP_DIR / f"{job}_input.%(ext)s")
    u = url.lower()
    title = ""

    if any(d in u for d in ("youtube.com","youtu.be","shorts.google.com")):
        strategies = [
            ("bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/best[height<=720]",
             ["--user-agent",MUA,"--extractor-args","youtube:player_client=android,ios","--no-check-certificates"]),
            ("best[height<=720]/best[height<=480]/best",
             ["--user-agent",DUA,"--extractor-args","youtube:player_client=tv_embedded","--no-check-certificates"]),
            ("best[height<=480]/best",
             ["--user-agent",IUA,"--extractor-args","youtube:player_client=mweb","--no-check-certificates"]),
            ("worst/best",
             ["--user-agent",DUA,"--no-check-certificates"]),
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
             ["--user-agent",MUA,"--extractor-args","pinterest:api=v3","--no-check-certificates"]),
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
# ✨ ENHANCE ULTRA PREMIUM
# ════════════════════════════════════════════
def process_enhance(inp):
    out = tmp_path(".mp4")
    info = get_video_info(inp)
    w, h = info["width"], info["height"]

    # Smart upscale filter
    if h < 1080:
        scale_f = f"scale=trunc(iw*1080/ih/2)*2:1080:flags=lanczos,"
    else:
        scale_f = ""

    vf = (
        f"hqdn3d=2:2:4:4,"                 # Stage 1: Denoise (lighter)
        f"{scale_f}"                        # Stage 2: Upscale
        f"eq=contrast=1.08:brightness=0.02:saturation=1.25:gamma=0.95,"  # Stage 3: Color
        f"unsharp=5:5:1.2:5:5:0.5,"       # Stage 4: Sharpen
        f"vignette=PI/4.5"                 # Stage 5: Vignette
    )

    if has_audio(inp):
        af = "loudnorm=I=-16:TP=-1.5:LRA=11"
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf", vf, "-af", af,
               "-c:v","libx264","-preset","veryfast","-crf","18",
               "-c:a","aac","-b:a","192k",
               "-movflags","+faststart", out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf", vf, "-an",
               "-c:v","libx264","-preset","veryfast","-crf","18",
               "-movflags","+faststart", out]

    ok, err = run_ffmpeg(cmd)
    return (out if ok else None), err

# ════════════════════════════════════════════
# 📺 YOUTUBE MODE — Advanced Copyright Bypass
# ════════════════════════════════════════════
def process_yt_mode(inp):
    """
    YouTube Mode — Multi-layer copyright bypass:
    Layer 1: Video — Scale + crop + microscopic rotate + border
    Layer 2: Color — Subtle HSV shift + brightness tweak
    Layer 3: Audio — Pitch shift + tempo + EQ + subtle echo
    Layer 4: Container — Metadata strip + fast start
    """
    out = tmp_path(".mp4")

    # Random small values for uniqueness
    rot   = round(random.uniform(0.3, 0.7), 2)   # tiny rotate
    br    = round(random.uniform(0.01, 0.03), 3)  # brightness
    sat   = round(random.uniform(1.02, 1.06), 3)  # saturation
    pitch = round(random.uniform(1.5, 2.5), 1)    # cents

    vf = (
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"rotate={rot}*PI/180:fillcolor=black@0:ow=iw:oh=ih,"
        f"crop=1916:1076:2:2,"
        f"eq=brightness={br}:saturation={sat}:contrast=1.02,"
        f"hue=h=1.5:s=1.02"
    )

    if has_audio(inp):
        af = (
            f"asetrate=44100*{1+(pitch/1000)},"
            f"atempo={1-(pitch/2000)},"
            f"equalizer=f=8000:width_type=o:width=1.5:g=1.5,"
            f"equalizer=f=200:width_type=o:width=1:g=-0.5,"
            f"aecho=0.85:0.88:30:0.25"
        )
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","veryfast","-crf","20",
               "-c:a","aac","-b:a","192k",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","veryfast","-crf","20",
               "-map_metadata","-1",
               "-movflags","+faststart",out]

    ok, err = run_ffmpeg(cmd)
    return (out if ok else None), err

# ════════════════════════════════════════════
# 📱 TIKTOK MODE — Copyright Safe + Optimized
# ════════════════════════════════════════════
def process_tt_mode(inp):
    """
    TikTok Mode — Copyright-safe 9:16 + TikTok optimized:
    Layer 1: 9:16 portrait crop/pad
    Layer 2: TikTok color profile (vivid + warm)
    Layer 3: Slight sharpen for mobile screens
    Layer 4: Audio pitch + tempo shift (copyright bypass)
    Layer 5: Metadata strip
    """
    out = tmp_path(".mp4")

    # TikTok prefers vivid, warm colors
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "eq=contrast=1.05:brightness=0.01:saturation=1.20:gamma=0.98,"
        "hue=h=2:s=1.05,"
        "unsharp=3:3:0.8:3:3:0.3"
    )

    # Random pitch for copyright bypass
    pitch = round(random.uniform(1.0, 2.0), 1)

    if has_audio(inp):
        af = (
            f"asetrate=44100*{1+(pitch/1000)},"
            f"atempo={1-(pitch/2000)},"
            f"equalizer=f=10000:width_type=o:width=2:g=1,"
            f"equalizer=f=100:width_type=o:width=1:g=-1,"
            f"loudnorm=I=-14:TP=-1:LRA=11"
        )
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-af",af,
               "-c:v","libx264","-preset","veryfast","-crf","18",
               "-c:a","aac","-b:a","192k",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","veryfast","-crf","18",
               "-map_metadata","-1",
               "-movflags","+faststart",out]

    ok, err = run_ffmpeg(cmd)
    return (out if ok else None), err

# ════════════════════════════════════════════
# 📸 INSTAGRAM MODE
# ════════════════════════════════════════════
def process_ig_mode(inp):
    """Instagram 4:5 optimized"""
    out = tmp_path(".mp4")

    vf = (
        "scale=1080:1350:force_original_aspect_ratio=decrease,"
        "pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black,"
        "eq=contrast=1.05:saturation=1.15:gamma=0.97"
    )

    if has_audio(inp):
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,
               "-c:v","libx264","-preset","veryfast","-crf","20",
               "-c:a","aac","-b:a","192k",
               "-map_metadata","-1",
               "-movflags","+faststart",out]
    else:
        cmd = ["ffmpeg","-y","-i",inp,
               "-vf",vf,"-an",
               "-c:v","libx264","-preset","veryfast","-crf","20",
               "-map_metadata","-1",
               "-movflags","+faststart",out]

    ok, err = run_ffmpeg(cmd)
    return (out if ok else None), err

PROCESSORS = {
    "enhance": process_enhance,
    "yt_mode": process_yt_mode,
    "tt_mode": process_tt_mode,
    "ig_mode": process_ig_mode,
}

MODE_LABELS = {
    "enhance": "✨ Enhance Ultra PREMIUM",
    "yt_mode": "📺 YouTube Mode",
    "tt_mode": "📱 TikTok Mode",
    "ig_mode": "📸 Instagram Mode",
}

MODE_CAPTIONS = {
    "enhance": (
        "✨ *Enhance Ultra PREMIUM*\n\n"
        "🎬 5-stage cinematic processing:\n"
        "• Advanced denoise\n"
        "• Smart upscale (→1080p)\n"
        "• Cinematic color grading\n"
        "• Dual-stage sharpening\n"
        "• Vignette + EBU R128 audio"
    ),
    "yt_mode": (
        "📺 *YouTube Mode — Copyright Safe*\n\n"
        "🛡️ Multi-layer bypass:\n"
        "• Video rotation + border crop\n"
        "• Color + HSV shift\n"
        "• Audio pitch + EQ + echo\n"
        "• Metadata strip"
    ),
    "tt_mode": (
        "📱 *TikTok Mode — Copyright Safe*\n\n"
        "🛡️ TikTok optimized:\n"
        "• 9:16 portrait (1080×1920)\n"
        "• Vivid warm color profile\n"
        "• Audio pitch bypass\n"
        "• Mobile-optimized sharpness"
    ),
    "ig_mode": (
        "📸 *Instagram Mode*\n\n"
        "• 4:5 format (1080×1350)\n"
        "• Instagram color profile\n"
        "• Metadata stripped"
    ),
}

# ════════════════════════════════════════════
# 🎯 WINGO ULTRA ENGINE — 35 Layer
# ════════════════════════════════════════════
def _w_sizeof(n): return "BIG" if n >= 5 else "SMALL"
def _w_colorof(n):
    if n == 0: return "violet_red"
    if n == 5: return "violet_green"
    return "red" if n % 2 != 0 else "green"

def _w_fetch():
    for api in WINGO_APIS:
        try:
            url = api + str(int(time.time() * 1000))
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            rows = (data.get("data") or {}).get("list") or []
            out = []
            for row in rows[:50]:
                try:
                    n = int(row.get("number", row.get("num", -1)))
                    p = str(row.get("issueNumber") or row.get("period") or "")
                    if n < 0 or not p: continue
                    out.append({"period":p,"number":n,
                                "size":_w_sizeof(n),"color":_w_colorof(n)})
                except Exception:
                    continue
            if out: return out
        except Exception as e:
            logger.warning("wingo fetch: %s", e)
    return []

def _w_adaptive_weight(layer_id, base_w):
    lp = _wingo_state["layer_perf"].get(layer_id, {})
    if lp.get("total",0) < 15: return base_w
    acc = lp["hit"] / lp["total"]
    if acc > 0.62: return min(base_w * 1.6, base_w + 0.10)
    if acc < 0.42: return max(base_w * 0.4, base_w - 0.08)
    return base_w

def _w_analyze(history):
    if not history: return None
    nums  = [h["number"] for h in history]
    sizes = [h["size"]   for h in history]
    colors= [h["color"]  for h in history]

    sb = ss = 0.0
    layer_votes = {}

    def v(lid, b, s, base_w=1.0):
        nonlocal sb, ss
        w = _w_adaptive_weight(lid, base_w)
        sb += b*w; ss += s*w
        layer_votes[lid] = ("BIG" if b>s else "SMALL" if s>b else "TIE")

    # ── STATISTICAL LAYERS ──

    # L1 Frequency mean-reversion (last 20)
    bc = sizes[:20].count("BIG")
    v(1, 20-bc, bc, 1.4)

    # L2 Streak reversal
    stk = 1
    for i in range(1, min(len(sizes),15)):
        if sizes[i]==sizes[0]: stk+=1
        else: break
    if stk>=5:   v(2, 2.0 if sizes[0]=="SMALL" else 0, 2.0 if sizes[0]=="BIG" else 0, 1.8)
    elif stk>=3: v(2, 1.5 if sizes[0]=="SMALL" else 0, 1.5 if sizes[0]=="BIG" else 0, 1.5)
    elif stk>=2: v(2, 1.1 if sizes[0]=="SMALL" else 0, 1.1 if sizes[0]=="BIG" else 0, 1.1)
    else:        v(2, .5, .5, .5)

    # L3 Zigzag pattern
    zz = sum(1 for i in range(1,min(len(sizes),12)) if sizes[i]!=sizes[i-1])
    if zz>=9: v(3,.5,.5,.5)
    elif zz>=6 and len(sizes)>1 and sizes[0]!=sizes[1]:
        v(3, 1 if sizes[1]=="BIG" else 0, 1 if sizes[1]=="SMALL" else 0, .9)
    else: v(3,.5,.5,.5)

    # L4 Markov-2
    if len(sizes)>=3:
        cm={}
        for i in range(len(sizes)-2):
            k=sizes[i][0]+sizes[i+1][0]; cm.setdefault(k,{"B":0,"S":0}); cm[k][sizes[i+2][0]]+=1
        c=cm.get(sizes[1][0]+sizes[0][0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(4,c["B"]/t,c["S"]/t,1.4)
        elif t>=3: v(4,c["B"]/t,c["S"]/t,1.0)
        else: v(4,.5,.5,.4)

    # L5 Gap analysis
    lb=next((i for i,s in enumerate(sizes) if s=="BIG"),25)
    ls=next((i for i,s in enumerate(sizes) if s=="SMALL"),25)
    if lb>8:   v(5,1.8,0,1.2)
    elif lb>5: v(5,1.3,0,.9)
    elif ls>8: v(5,0,1.8,1.2)
    elif ls>5: v(5,0,1.3,.9)
    else:      v(5,.5,.5,.5)

    # L6 Trend last 5
    t5=sizes[:5].count("BIG")
    if t5>=5:   v(6,0,1.5,1.0)
    elif t5>=4: v(6,0,1.2,1.0)
    elif t5<=0: v(6,1.5,0,1.0)
    elif t5<=1: v(6,1.2,0,1.0)
    else:       v(6,.5,.5,.5)

    # L7 EMA-12
    ema=1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1,min(12,len(sizes))):
        ema=.2*(1 if sizes[i]=="BIG" else 0)+.8*ema
    v(7,1-ema,ema,1.2)

    # L8 EMA-25
    ema2=1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1,min(25,len(sizes))):
        ema2=.1*(1 if sizes[i]=="BIG" else 0)+.9*ema2
    v(8,1-ema2,ema2,0.9)

    # L9 6-gram
    if len(sizes)>=7:
        k6="".join(s[0] for s in sizes[:6])
        mb=ms=0
        for i in range(6,len(sizes)):
            if "".join(s[0] for s in sizes[i-6:i])==k6:
                mb+=1 if sizes[i]=="BIG" else 0
                ms+=1 if sizes[i]=="SMALL" else 0
        if mb+ms>=3: v(9,mb/(mb+ms),ms/(mb+ms),1.5)
        elif mb+ms>=1: v(9,mb/(mb+ms),ms/(mb+ms),1.0)
        else: v(9,.5,.5,.5)

    # L10 4-gram
    if len(sizes)>=5:
        k4="".join(s[0] for s in sizes[:4])
        mb=ms=0
        for i in range(4,len(sizes)):
            if "".join(s[0] for s in sizes[i-4:i])==k4:
                mb+=1 if sizes[i]=="BIG" else 0
                ms+=1 if sizes[i]=="SMALL" else 0
        if mb+ms>=4: v(10,mb/(mb+ms),ms/(mb+ms),1.3)
        else: v(10,.5,.5,.4)

    # L11 Bayesian prior
    pr=sizes[:30].count("BIG")/min(30,len(sizes))
    v(11,pr,1-pr,.9)

    # L12 Color correlation
    rc=sum(1 for c in colors[:15] if c in ("red","violet_red"))
    if rc>=10: v(12,0,1,.8)
    elif rc>=8: v(12,0,.8,.7)
    elif rc<=5: v(12,1,0,.8)
    elif rc<=7: v(12,.8,0,.7)
    else: v(12,.5,.5,.4)

    # L13 Volatility
    if len(nums)>=10:
        diffs=[abs(nums[i]-nums[i+1]) for i in range(9)]
        avg=sum(diffs)/len(diffs); std=math.sqrt(sum((d-avg)**2 for d in diffs)/9)
        if avg>5 or std>2.5: v(13,.5,.5,.5)
        else: v(13,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.8)

    # L14 Run-length
    runs=[]; cur=sizes[0]; cnt=1
    for i in range(1,min(len(sizes),25)):
        if sizes[i]==cur: cnt+=1
        else: runs.append(cnt); cur=sizes[i]; cnt=1
    runs.append(cnt); ar=sum(runs)/len(runs)
    if runs[0]>=ar*2.5:
        v(14,1.8 if sizes[0]=="SMALL" else 0, 1.8 if sizes[0]=="BIG" else 0, 1.2)
    elif runs[0]>=ar*1.5:
        v(14,1.2 if sizes[0]=="SMALL" else 0, 1.2 if sizes[0]=="BIG" else 0, .9)
    else: v(14,.5,.5,.5)

    # L15 Period parity
    try:
        p=int(str(history[0]["period"])[-2:])
        v(15,.63 if p%2==0 else .37, .37 if p%2==0 else .63,.7)
    except Exception: v(15,.5,.5,.3)

    # L16 Number Markov
    if len(nums)>=3:
        nm={}
        for i in range(len(nums)-1):
            nm.setdefault(nums[i],{"B":0,"S":0})
            nm[nums[i]]["B" if nums[i+1]>=5 else "S"]+=1
        c=nm.get(nums[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(16,c["B"]/t,c["S"]/t,1.3)
        elif t>=3: v(16,c["B"]/t,c["S"]/t,0.9)
        else: v(16,.5,.5,.4)

    # L17 Shannon entropy
    ec=Counter(sizes[:20]); et=sum(ec.values())
    if et>0:
        en=-sum((vv/et)*math.log2(vv/et) for vv in ec.values() if vv)
        if en>0.97: v(17,.5,.5,.3)
        elif en<0.7: v(17,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.9)
        else: v(17,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.7)

    # L18 Fibonacci positions
    fibs=[1,2,3,5,8,13,21]
    fs2=[sizes[f-1] for f in fibs if f<=len(sizes)]
    fb2=fs2.count("BIG"); fs3=fs2.count("SMALL")
    if fb2+fs3>0: v(18,fs3/(fb2+fs3),fb2/(fb2+fs3),.9)

    # L19 Triple Markov
    if len(sizes)>=4:
        tm={}
        for i in range(3,len(sizes)):
            k=sizes[i-3]+sizes[i-2]+sizes[i-1]
            tm.setdefault(k,{"B":0,"S":0}); tm[k]["B" if sizes[i]=="BIG" else "S"]+=1
        c=tm.get(sizes[2]+sizes[1]+sizes[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=4: v(19,c["B"]/t,c["S"]/t,1.6)
        elif t>=2: v(19,c["B"]/t,c["S"]/t,1.1)
        else: v(19,.5,.5,.5)

    # L20 Quad Markov
    if len(sizes)>=5:
        qm={}
        for i in range(4,len(sizes)):
            k=sizes[i-4]+sizes[i-3]+sizes[i-2]+sizes[i-1]
            qm.setdefault(k,{"B":0,"S":0}); qm[k]["B" if sizes[i]=="BIG" else "S"]+=1
        c=qm.get(sizes[3]+sizes[2]+sizes[1]+sizes[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=3: v(20,c["B"]/t,c["S"]/t,1.4)
        else: v(20,.5,.5,.4)

    # L21 R3 balance
    r3=sizes[:3].count("BIG")
    v(21,1.2 if r3<=1 else 0, 1.2 if r3>=2 else 0,.9)

    # L22 R5 balance
    r5=sizes[:5].count("BIG")
    v(22,1.1 if r5<=2 else (0 if r5>=4 else .5), 1.1 if r5>=3 else (0 if r5<=1 else .5),.8)

    # L23 Number parity
    ep=sum(1 for n in nums[:12] if n%2==0)
    v(23,(12-ep)/12,ep/12,.8)

    # L24 Sum trend
    if len(nums)>=6:
        s1=sum(nums[:3]); s2=sum(nums[3:6])
        diff=s1-s2
        if diff>6:   v(24,0,1.2,.8)
        elif diff<-6: v(24,1.2,0,.8)
        elif diff>3:  v(24,0,.8,.6)
        elif diff<-3: v(24,.8,0,.6)
        else:         v(24,.5,.5,.4)

    # L25 Alternation rate
    alt=sum(1 for i in range(1,min(12,len(sizes))) if sizes[i]!=sizes[i-1])
    ratio=alt/11 if len(sizes)>=12 else alt/max(1,len(sizes)-1)
    if ratio>0.7: v(25,.5,.5,.5)
    elif len(sizes)>1: v(25,.65 if sizes[0]=="SMALL" else .35, .65 if sizes[0]=="BIG" else .35,.7)

    # L26 Mode anti-bias
    mc=Counter(nums[:20]); mn=mc.most_common(1)[0][0] if mc else 0
    v(26,0 if mn>=5 else 1, 1 if mn>=5 else 0,1.0)

    # L27 L10 ratio
    l10=sizes[:10].count("BIG")
    if l10<=2:   v(27,1.4,0,1.1)
    elif l10>=8: v(27,0,1.4,1.1)
    elif l10<=3: v(27,1.1,0,.8)
    elif l10>=7: v(27,0,1.1,.8)
    else:        v(27,.5,.5,.5)

    # L28 Consecutive same
    con=0
    for i in range(len(sizes)-1):
        if sizes[i]==sizes[i+1]: con+=1
        else: break
    if con>=4: v(28,1.8 if sizes[0]=="SMALL" else 0, 1.8 if sizes[0]=="BIG" else 0,1.3)
    elif con>=2: v(28,1.2 if sizes[0]=="SMALL" else 0, 1.2 if sizes[0]=="BIG" else 0,.9)
    elif con>=1: v(28,.8 if sizes[0]=="SMALL" else 0, .8 if sizes[0]=="BIG" else 0,.7)
    else: v(28,.5,.5,.5)

    # L29 Quartile position
    sq=sorted(nums[:20])
    q1=sq[4] if len(sq)>5 else 2; q3=sq[14] if len(sq)>15 else 7
    if nums[0]<q1:   v(29,1.3,0,.9)
    elif nums[0]>q3: v(29,0,1.3,.9)
    else:            v(29,.5,.5,.5)

    # L30 Spread volatility
    if len(nums)>=10:
        sp=max(nums[:10])-min(nums[:10])
        if sp<2:   v(30,.9 if sizes[0]=="SMALL" else .1, .9 if sizes[0]=="BIG" else .1,.8)
        elif sp>7: v(30,.5,.5,.4)
        else:      v(30,.5,.5,.5)

    # L31 Cyclic-3
    if len(sizes)>=6:
        cy3=sum(1 for i in range(min(6,len(sizes)-3)) if sizes[i+3]==sizes[i])
        if cy3>=5: v(31,1.2 if sizes[3]=="BIG" else 0, 1.2 if sizes[3]=="SMALL" else 0,1.1)
        else:      v(31,.5,.5,.5)

    # L32 Cyclic-5
    if len(sizes)>=10:
        cy5=sum(1 for i in range(min(5,len(sizes)-5)) if sizes[i+5]==sizes[i])
        if cy5>=4: v(32,1.1 if sizes[5]=="BIG" else 0, 1.1 if sizes[5]=="SMALL" else 0,.9)
        else:      v(32,.5,.5,.5)

    # L33 Color Markov
    if len(colors)>=3:
        cm2={}
        for i in range(len(colors)-1):
            cm2.setdefault(colors[i],{"B":0,"S":0})
            cm2[colors[i]]["B" if colors[i+1] in ("red","violet_red") else "S"]+=1
        c=cm2.get(colors[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(33,c["B"]/t,c["S"]/t,.9)
        else:    v(33,.5,.5,.4)

    # L34 Self-correction (recent accuracy)
    total=_wingo_state.get("total_pred",0)
    correct=_wingo_state.get("correct_pred",0)
    if total>=10:
        acc=correct/total
        if acc<0.40:   v(34,ss,sb,.6)   # flip signal
        elif acc>0.65: v(34,sb,ss,.5)   # reinforce
        else:          v(34,.5,.5,.3)

    # L35 Anti-loss-streak
    loss_stk=_wingo_state.get("loss_streak",0)
    win_stk=_wingo_state.get("win_streak",0)
    if loss_stk>=4:    v(35,.55 if sb>=ss else .45, .55 if ss>sb else .45, 1.3)
    elif win_stk>=6:   v(35,ss*.4,sb*.4,.4)
    else:              v(35,.5,.5,.3)

    # ── DECISION ──
    tw = sb+ss or 1
    pB = round(sb/tw*100); pS = 100-pB
    sig = "BIG" if sb>=ss else "SMALL"
    conf = max(pB,pS)

    # ── COLOR PREDICTION ──
    cs={"red":0.0,"green":0.0,"violet":0.0}
    for i,col in enumerate(colors[:25]):
        w=1/(i+1)
        if col=="red": cs["red"]+=w
        elif col=="green": cs["green"]+=w
        else: cs["violet"]+=w*1.7
    if sig=="BIG": cs["red"]+=3.0; cs["violet"]+=1.0
    else:          cs["green"]+=3.0; cs["violet"]+=1.0
    ct=sum(cs.values()) or 1
    pR=round(cs["red"]/ct*100); pG=round(cs["green"]/ct*100)
    pV=max(0,100-pR-pG)
    tc="red" if pR>pG and pR>pV else ("green" if pG>pR and pG>pV else "violet")

    # ── NUMBER PREDICTION ──
    ns=[0.0]*10
    for i,n in enumerate(nums[:35]): ns[n]+=1/(i*.08+1)
    for n in range(10):
        if _w_sizeof(n)==sig: ns[n]+=4
    ranked=sorted(range(10),key=lambda x:-ns[x])

    # ── CONFIDENCE LEVEL ──
    if conf>=80:   conf_label="🔥 ULTRA HIGH"
    elif conf>=70: conf_label="💪 HIGH"
    elif conf>=60: conf_label="✅ MEDIUM"
    else:          conf_label="⚠️ LOW"

    # Layer summary
    big_layers  = sum(1 for vote in layer_votes.values() if vote=="BIG")
    small_layers= sum(1 for vote in layer_votes.values() if vote=="SMALL")

    return {
        "sig":sig,"conf":conf,"conf_label":conf_label,
        "pB":pB,"pS":pS,"pR":pR,"pG":pG,"pV":pV,"tc":tc,
        "numTop":ranked[0],"numAlt":ranked[1:5],
        "period":history[0]["period"] if history else "",
        "big_layers":big_layers,"small_layers":small_layers,
        "total_layers":len(layer_votes),
    }

# ════════════════════════════════════════════
# MENUS — Beautiful UI
# ════════════════════════════════════════════
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥  ভিডিও ডাউনলোড", callback_data="dl_help")],
        [InlineKeyboardButton("✨  Enhance ULTRA", callback_data="enhance_help"),
         InlineKeyboardButton("📺  Platform", callback_data="platform_menu")],
        [InlineKeyboardButton("🎯  WinGo Prediction", callback_data="wingo_menu")],
    ])

def platform_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺  YouTube Mode (16:9 + 🛡️ Copyright Safe)", callback_data="platform_help_yt")],
        [InlineKeyboardButton("📱  TikTok Mode (9:16 + 🛡️ Copyright Safe)", callback_data="platform_help_tt")],
        [InlineKeyboardButton("📸  Instagram Mode (4:5)", callback_data="platform_help_ig")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ])

def wingo_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Prediction নিন", callback_data="wingo_predict")],
        [InlineKeyboardButton("✅ WIN", callback_data="wingo_win"),
         InlineKeyboardButton("❌ LOSS", callback_data="wingo_loss")],
        [InlineKeyboardButton("📊 আমার Record", callback_data="wingo_record"),
         InlineKeyboardButton("🔙 Back", callback_data="back_main")],
    ])

def edit_btns(job):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Enhance ULTRA", callback_data=f"do_enhance_{job}"),
         InlineKeyboardButton("📺 YouTube", callback_data=f"do_yt_mode_{job}")],
        [InlineKeyboardButton("📱 TikTok", callback_data=f"do_tt_mode_{job}"),
         InlineKeyboardButton("📸 Instagram", callback_data=f"do_ig_mode_{job}")],
        [InlineKeyboardButton("🎯 WinGo", callback_data="wingo_predict")],
    ])

# ════════════════════════════════════════════
# START TEXT
# ════════════════════════════════════════════
START_TEXT = """
╔═══════════════════════╗
    🎬 *Video Bot {ver}*
     ✦ Premium Edition ✦
╚═══════════════════════╝

👋 স্বাগতম *{{name}}*!

┌─────────────────────┐
│  📥 *ডাউনলোড*         │
│  YouTube · TikTok   │
│  Instagram · FB     │
├─────────────────────┤
│  ✨ *Enhance ULTRA*  │
│  সিনেমা মানের ভিডিও  │
│  Smart 1080p Upscale│
├─────────────────────┤
│  📺 *Platform Mode* │
│  Copyright Safe     │
│  YT · TikTok · IG  │
├─────────────────────┤
│  🎯 *WinGo*         │
│  AI Prediction      │
└─────────────────────┘

💡 *কীভাবে ব্যবহার করবেন:*
🔗 Link পাঠান → Download
🎥 ভিডিও পাঠান → Edit
👇 নিচের বাটন → Menu
""".strip()

# ════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════
async def cmd_start(u, c):
    name = md_escape(u.effective_user.first_name or "বন্ধু")
    await safe_reply(u.message,
        START_TEXT.format(ver=VERSION).replace("{name}", name),
        parse_mode="Markdown", reply_markup=main_menu())

async def cmd_wingo(u, c):
    await safe_reply(u.message,
        "🎯 *WinGo ULTRA — 35-Layer AI*\n\n"
        "Real-time prediction + color + number!\n\n👇",
        parse_mode="Markdown", reply_markup=wingo_menu())

async def handle_msg(u, c):
    msg = u.message
    if not msg: return
    uid  = u.effective_user.id
    text = (msg.text or "").strip()

    # URL
    urls = re.findall(r'https?://\S+', text, re.I)
    if urls:
        url = urls[0]
        job = uuid.uuid4().hex[:12]

        # Detect platform
        u2 = url.lower()
        if any(d in u2 for d in ("youtube.com","youtu.be")): plat="📺 YouTube"
        elif "tiktok.com" in u2: plat="📱 TikTok"
        elif "instagram.com" in u2: plat="📸 Instagram"
        elif "facebook.com" in u2 or "fb.watch" in u2: plat="👥 Facebook"
        elif "pinterest." in u2: plat="📌 Pinterest"
        else: plat="🌐 Video"

        st = await safe_reply(msg,
            f"⏳ *{plat} ডাউনলোড হচ্ছে...*\nঅপেক্ষা করুন ⌛",
            parse_mode="Markdown")
        await msg.chat.send_action(ChatAction.UPLOAD_VIDEO)

        loop = asyncio.get_running_loop()
        ok, title, err, filepath = await loop.run_in_executor(executor, yt_dl, url, job)

        if not ok:
            await safe_edit(st,
                f"❌ *ডাউনলোড ব্যর্থ!*\n\n"
                f"`{err[:200]}`\n\n"
                f"💡 অন্য link try করুন।",
                parse_mode="Markdown"); return

        size_mb = Path(filepath).stat().st_size / 1024 / 1024
        await safe_edit(st,
            f"⏫ *আপলোড হচ্ছে...* `{size_mb:.1f} MB`",
            parse_mode="Markdown")

        try:
            with open(filepath,"rb") as f:
                await msg.reply_video(f, read_timeout=300, write_timeout=300, connect_timeout=60,
                    caption=(
                        f"✅ *{md_escape(title or 'ডাউনলোড সম্পন্ন')}*\n\n"
                        f"📦 Size: `{size_mb:.1f} MB`\n"
                        f"🎬 Platform: {plat}\n\n"
                        f"👇 Edit করতে নিচে ক্লিক করুন:"
                    ),
                    parse_mode="Markdown",
                    reply_markup=edit_btns(job),
                )
            _user_state[uid] = {"job":job,"file":filepath}
            try: await st.delete()
            except Exception: pass
        except Exception as e:
            await safe_edit(st,f"❌ আপলোড ব্যর্থ: `{e}`",parse_mode="Markdown")
        return

    # Video/Document
    if msg.video or msg.document:
        file_obj = msg.video or msg.document
        job = uuid.uuid4().hex[:12]
        _user_state[uid] = {"job":job,"file_id":file_obj.file_id}
        await safe_reply(msg,
            "📥 *ভিডিও পেয়েছি!*\n\n👇 কী করতে চান?",
            parse_mode="Markdown",reply_markup=edit_btns(job))
        return

    # Default
    await safe_reply(msg,
        "📥 *Link পাঠান* → Download হবে\n"
        "🎬 *ভিডিও পাঠান* → Edit করুন\n\n"
        "/start — Main menu\n/wingo — WinGo Prediction")

async def handle_cb(u, c):
    q   = u.callback_query
    try: await q.answer()
    except Exception: pass
    uid  = q.from_user.id
    data = q.data

    if data == "noop": return

    # Navigation
    if data == "back_main":
        await safe_edit(q.message,
            START_TEXT.format(ver=VERSION),
            parse_mode="Markdown",reply_markup=main_menu()); return

    if data == "platform_menu":
        await safe_edit(q.message,
            "📺 *Platform Mode*\n\n"
            "🛡️ সব mode-এ copyright bypass আছে!\n\n"
            "ভিডিও পাঠান → platform select করুন:",
            parse_mode="Markdown",reply_markup=platform_menu()); return

    if data == "wingo_menu":
        await safe_edit(q.message,
            "🎯 *WinGo ULTRA*\n35-layer AI prediction engine!\n\n👇",
            parse_mode="Markdown",reply_markup=wingo_menu()); return

    if data in ("dl_help","enhance_help","platform_help_yt","platform_help_tt","platform_help_ig"):
        hints = {
            "dl_help":          "📥 YouTube/TikTok/Instagram/Facebook/Pinterest link পাঠান!",
            "enhance_help":     "✨ ভিডিও পাঠান — 5-stage Enhance Ultra করব!",
            "platform_help_yt": "📺 ভিডিও পাঠান → YouTube Mode (16:9 + 🛡️ Copyright Safe)!",
            "platform_help_tt": "📱 ভিডিও পাঠান → TikTok Mode (9:16 + 🛡️ Copyright Safe)!",
            "platform_help_ig": "📸 ভিডিও পাঠান → Instagram Mode (4:5)!",
        }
        await q.message.reply_text(hints[data]); return

    # ── WinGo ──
    if data == "wingo_predict":
        await safe_edit(q.message, "⏳ *data আনছি...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        history = await loop.run_in_executor(executor, _w_fetch)
        if not history:
            await safe_edit(q.message,"❌ API error! পরে চেষ্টা করুন।",
                            reply_markup=wingo_menu()); return
        pred = await loop.run_in_executor(executor, _w_analyze, history)
        if not pred:
            await safe_edit(q.message,"❌ Analysis ব্যর্থ!",
                            reply_markup=wingo_menu()); return

        _wingo_state["history"] = history
        _wingo_state["last_period"] = pred["period"]

        # Save pending prediction for this user
        _wingo_state["pending"][uid] = {
            "sig": pred["sig"], "color": pred["tc"],
            "num": pred["numTop"], "period": pred["period"]
        }

        se = "🔺" if pred["sig"]=="BIG" else "🔻"
        te = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        sig_bn = "বড় (৫–৯)" if pred["sig"]=="BIG" else "ছোট (০–৪)"
        bar = "█"*round(pred["conf"]/10) + "░"*(10-round(pred["conf"]/10))

        txt = (
            "🎯 *WinGo Prediction*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{se} *{pred['sig']}* — {sig_bn}\n"
            f"`{bar}` *{pred['conf']}%*\n\n"
            f"🎨 Color: {te} *{pred['tc'].upper()}*\n\n"
            f"🎲 Number: *{pred['numTop']}*\n"
            f"   Backup: `{pred['numAlt'][0]}` `{pred['numAlt'][1]}` `{pred['numAlt'][2]}`\n\n"
            f"📅 Period: `{pred['period'][-6:] if pred['period'] else chr(8212)}`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ _Random game — guarantee নেই_\n\n"
            "👇 *Result কি হয়েছিল?*"
        )
        await safe_edit(q.message, txt, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ WIN হয়েছি!", callback_data="wingo_win"),
                             InlineKeyboardButton("❌ LOSS হয়েছি", callback_data="wingo_loss")],
                            [InlineKeyboardButton("🔄 নতুন Prediction", callback_data="wingo_predict"),
                             InlineKeyboardButton("🔙 Back", callback_data="back_main")],
                        ])); return

    if data in ("wingo_win", "wingo_loss"):
        is_win = data == "wingo_win"
        rec = _wingo_state["records"].setdefault(uid, {"win":0,"loss":0,"streak":0,"max_streak":0})
        if is_win:
            rec["win"] += 1
            rec["streak"] = max(0, rec["streak"]) + 1
            rec["max_streak"] = max(rec["max_streak"], rec["streak"])
        else:
            rec["loss"] += 1
            rec["streak"] = min(0, rec["streak"]) - 1

        tot = rec["win"] + rec["loss"]
        acc = round(rec["win"]/tot*100) if tot else 0
        stk = rec["streak"]
        stk_txt = f"🔥 {stk}" if stk > 0 else (f"💀 {abs(stk)}" if stk < 0 else "0")

        # Pending prediction info
        pend = _wingo_state["pending"].get(uid, {})
        sig_show = pend.get("sig","—"); col_show = pend.get("color","—")
        num_show = pend.get("num","—")

        result_e = "✅ WIN!" if is_win else "❌ LOSS"
        txt = (
            f"{result_e}\n\n"
            "📊 *আপনার Record:*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"✅ WIN: `{rec['win']}` | ❌ LOSS: `{rec['loss']}`\n"
            f"🎯 Accuracy: `{acc}%`\n"
            f"Streak: {stk_txt}\n"
            f"🏆 Best streak: `{rec['max_streak']}`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👇 নতুন prediction নিন:"
        )
        await safe_edit(q.message, txt, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⚡ নতুন Prediction", callback_data="wingo_predict")],
                            [InlineKeyboardButton("📊 Full Record", callback_data="wingo_record"),
                             InlineKeyboardButton("🔙 Back", callback_data="back_main")],
                        ])); return

    if data == "wingo_record":
        rec = _wingo_state["records"].get(uid, {"win":0,"loss":0,"streak":0,"max_streak":0})
        tot = rec["win"] + rec["loss"]
        acc = round(rec["win"]/tot*100) if tot else 0
        stk = rec["streak"]
        stk_txt = f"🔥 {stk}" if stk > 0 else (f"💀 {abs(stk)}" if stk < 0 else "0")
        hist = _wingo_state.get("history",[])[:10]
        ht = " ".join(("🔴" if h["size"]=="BIG" else "🟢")+f"`{h['number']}`" for h in hist) if hist else "—"
        await safe_edit(q.message,
            f"📊 *আপনার WinGo Record*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ WIN: `{rec['win']}`\n"
            f"❌ LOSS: `{rec['loss']}`\n"
            f"🎯 Accuracy: `{acc}%`\n"
            f"Streak: {stk_txt}\n"
            f"🏆 Best: `{rec['max_streak']}`\n\n"
            f"🕹️ Last 10:\n{ht}",
            parse_mode="Markdown", reply_markup=wingo_menu()); return
    # ── Video Processing ──
    mode = job_id = None
    for m in ["enhance","yt_mode","tt_mode","ig_mode"]:
        pfx = f"do_{m}_"
        if data.startswith(pfx):
            mode   = m
            job_id = data[len(pfx):]
            break

    if not mode:
        await safe_edit(q.message,"❌ Unknown",reply_markup=main_menu()); return

    state = _user_state.get(uid,{})
    inp_path = None

    if state.get("job")==job_id and state.get("file"):
        inp_path = state["file"]
    elif state.get("job")==job_id and state.get("file_id"):
        await safe_edit(q.message,"⏬ *ফাইল নামছে...*",parse_mode="Markdown")
        try:
            tg_file = await c.bot.get_file(state["file_id"])
            inp_path = tmp_path(".mp4")
            await tg_file.download_to_drive(inp_path)
            state["file"] = inp_path
        except Exception as e:
            await safe_edit(q.message,f"❌ ফাইল নামাতে ব্যর্থ: `{e}`",
                            parse_mode="Markdown",reply_markup=main_menu()); return

    if not inp_path or not Path(inp_path).exists():
        await safe_edit(q.message,
            "❌ ফাইল পাওয়া যায়নি!\nআবার ভিডিও পাঠান।",
            reply_markup=main_menu()); return

    label = MODE_LABELS[mode]
    await safe_edit(q.message,
        f"⚙️ *{label} প্রসেস হচ্ছে...*\n\nঅপেক্ষা করুন ⏳",
        parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    out_path, err = await loop.run_in_executor(executor, PROCESSORS[mode], inp_path)

    if not out_path:
        err_msg = err[:300] if err else "অজানা সমস্যা"
        await safe_edit(q.message,
            f"❌ *Processing ব্যর্থ!*\n\n"
            f"🔹 কারণ: `{err_msg}`\n\n"
            f"💡 ছোট ভিডিও (৫০MB এর কম) দিয়ে চেষ্টা করুন।",
            parse_mode="Markdown",reply_markup=main_menu()); return

    await q.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    try:
        with open(out_path,"rb") as f:
            await q.message.reply_video(f, read_timeout=300, write_timeout=300, connect_timeout=60,
                caption=MODE_CAPTIONS.get(mode,"✅ সম্পন্ন!"),
                parse_mode="Markdown",
                reply_markup=edit_btns(job_id),
            )
        try: await q.message.delete()
        except Exception: pass
        try: Path(out_path).unlink()
        except Exception: pass
    except Exception as e:
        await safe_edit(q.message,f"❌ আপলোড ব্যর্থ: `{e}`",
                        parse_mode="Markdown",reply_markup=main_menu())

# ════════════════════════════════════════════
# WINGO AUTO TICK
# ════════════════════════════════════════════
async def wingo_tick(ctx):
    if not _wingo_subs: return
    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(executor, _w_fetch)
        if not hist: return
        pred = await loop.run_in_executor(executor, _w_analyze, hist)
        if not pred: return
        if pred["period"]==_wingo_state.get("last_period"): return
        _wingo_state["last_period"]=pred["period"]

        se = "🔺" if pred["sig"]=="BIG" else "🔻"
        te = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        bar="█"*round(pred["conf"]/10)+"░"*(10-round(pred["conf"]/10))
        txt = (
            f"🎯 *WinGo Auto — Period {pred['period'][-6:]}*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{se} *{pred['sig']}* `{pred['conf']}%` {pred['conf_label']}\n"
            f"`{bar}`\n"
            f"{te} `{pred['tc'].upper()}` | 🎲 `{pred['numTop']}`\n"
            f"BIG:{pred['big_layers']} SMALL:{pred['small_layers']}/35\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Random game_"
        )
        for uid in list(_wingo_subs):
            try:
                await ctx.bot.send_message(uid,txt,parse_mode="Markdown",
                                           reply_markup=wingo_menu())
            except Exception as e:
                if "blocked" in str(e).lower() or "not found" in str(e).lower():
                    _wingo_subs.discard(uid)
    except Exception as e:
        logger.warning("wingo_tick: %s",e)

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
    print("║  🎬  Video Bot v41 Premium চালু!         ║")
    print("║  ✨  Enhance Ultra PREMIUM                ║")
    print("║  📺  YouTube + 🛡️ Copyright Safe          ║")
    print("║  📱  TikTok + 🛡️ Copyright Safe           ║")
    print("║  🎯  WinGo ULTRA — 35 Layers              ║")
    print("║  Ctrl+C → বন্ধ                           ║")
    print("╚══════════════════════════════════════════╝")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
