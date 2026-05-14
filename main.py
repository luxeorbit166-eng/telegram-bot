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
        # আসল error প্রথম দিকে থাকে
        stderr = r.stderr or ""
        lines = [l for l in stderr.splitlines() if "error" in l.lower() or "invalid" in l.lower() or "failed" in l.lower()]
        err = "\n".join(lines[:5]) if lines else stderr[:300]
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
    grain  = round(random.uniform(8, 14), 1)
    pitch  = round(random.uniform(1.5, 3.0), 2)

    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setpts={1/speed}*PTS,"
        f"eq=contrast=1.06:brightness={br}:saturation={sat}:gamma=0.97,"
        f"hue=h={hue}:s=1.03,"
        f"crop=1078:1918:1:1,"
        f"scale=1080:1920,"
        f"unsharp=3:3:0.6:3:3:0.2,"
        f"noise=alls={grain}:allf=t+u"
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
        "📱 *TikTok Mode — Copyright Safe*\n\n"
        "✅ 7-layer bypass:\n"
        "• 9:16 portrait (1080×1920)\n"
        "• Speed micro-shift\n"
        "• Color + hue shift\n"
        "• Film grain overlay\n"
        "• Audio pitch + EQ + echo\n"
        "• Metadata stripped\n\n"
        "❌ Copyright আসবে না\n"
        "❌ Eligible for You আসবে না"
    ),
    "enhance": (
        "✨ *Enhance ULTRA*\n\n"
        "🎬 Cinematic processing:\n"
        "• Denoise + color grade\n"
        "• Smart upscale → 1080p\n"
        "• Sharpening + vignette\n"
        "• EBU R128 audio"
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
            rows = []
            if isinstance(data, dict):
                inner = data.get("data") or data.get("result") or {}
                if isinstance(inner, dict):
                    rows = inner.get("list") or inner.get("records") or []
                elif isinstance(inner, list):
                    rows = inner
            out = []
            for row in rows[:50]:
                try:
                    n = int(row.get("number") or row.get("num") or row.get("winNumber") or -1)
                    p = str(row.get("issueNumber") or row.get("period") or row.get("issue") or "")
                    if n < 0 or not p: continue
                    # API থেকে সরাসরি color নাও, না পেলে নিজে হিসাব করো
                    api_color = str(row.get("color") or "").lower().strip()
                    if api_color in ("red","green","violet","violet_red","violet_green"):
                        color = api_color
                    else:
                        color = _w_colorof(n)
                    out.append({"period":p,"number":n,"size":_w_sizeof(n),"color":color})
                except Exception:
                    continue
            if out:
                logger.info("WinGo: %d records from %s", len(out), api)
                return out
        except Exception as e:
            logger.warning("wingo fetch failed [%s]: %s", api, e)
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

    bc = sizes[:20].count("BIG"); v(1, 20-bc, bc, 1.4)
    stk = 1
    for i in range(1, min(len(sizes),15)):
        if sizes[i]==sizes[0]: stk+=1
        else: break
    if stk>=5:   v(2, 2.0 if sizes[0]=="SMALL" else 0, 2.0 if sizes[0]=="BIG" else 0, 1.8)
    elif stk>=3: v(2, 1.5 if sizes[0]=="SMALL" else 0, 1.5 if sizes[0]=="BIG" else 0, 1.5)
    elif stk>=2: v(2, 1.1 if sizes[0]=="SMALL" else 0, 1.1 if sizes[0]=="BIG" else 0, 1.1)
    else:        v(2, .5, .5, .5)
    zz = sum(1 for i in range(1,min(len(sizes),12)) if sizes[i]!=sizes[i-1])
    if zz>=9: v(3,.5,.5,.5)
    elif zz>=6 and len(sizes)>1 and sizes[0]!=sizes[1]:
        v(3, 1 if sizes[1]=="BIG" else 0, 1 if sizes[1]=="SMALL" else 0, .9)
    else: v(3,.5,.5,.5)
    if len(sizes)>=3:
        cm={}
        for i in range(len(sizes)-2):
            k=sizes[i][0]+sizes[i+1][0]; cm.setdefault(k,{"B":0,"S":0}); cm[k][sizes[i+2][0]]+=1
        c=cm.get(sizes[1][0]+sizes[0][0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(4,c["B"]/t,c["S"]/t,1.4)
        elif t>=3: v(4,c["B"]/t,c["S"]/t,1.0)
        else: v(4,.5,.5,.4)
    lb=next((i for i,s in enumerate(sizes) if s=="BIG"),25)
    ls=next((i for i,s in enumerate(sizes) if s=="SMALL"),25)
    if lb>8: v(5,1.8,0,1.2)
    elif lb>5: v(5,1.3,0,.9)
    elif ls>8: v(5,0,1.8,1.2)
    elif ls>5: v(5,0,1.3,.9)
    else: v(5,.5,.5,.5)
    t5=sizes[:5].count("BIG")
    if t5>=5: v(6,0,1.5,1.0)
    elif t5>=4: v(6,0,1.2,1.0)
    elif t5<=0: v(6,1.5,0,1.0)
    elif t5<=1: v(6,1.2,0,1.0)
    else: v(6,.5,.5,.5)
    ema=1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1,min(12,len(sizes))): ema=.2*(1 if sizes[i]=="BIG" else 0)+.8*ema
    v(7,1-ema,ema,1.2)
    ema2=1.0 if sizes[0]=="BIG" else 0.0
    for i in range(1,min(25,len(sizes))): ema2=.1*(1 if sizes[i]=="BIG" else 0)+.9*ema2
    v(8,1-ema2,ema2,0.9)
    if len(sizes)>=7:
        k6="".join(s[0] for s in sizes[:6]); mb=ms=0
        for i in range(6,len(sizes)):
            if "".join(s[0] for s in sizes[i-6:i])==k6:
                mb+=1 if sizes[i]=="BIG" else 0; ms+=1 if sizes[i]=="SMALL" else 0
        if mb+ms>=3: v(9,mb/(mb+ms),ms/(mb+ms),1.5)
        elif mb+ms>=1: v(9,mb/(mb+ms),ms/(mb+ms),1.0)
        else: v(9,.5,.5,.5)
    if len(sizes)>=5:
        k4="".join(s[0] for s in sizes[:4]); mb=ms=0
        for i in range(4,len(sizes)):
            if "".join(s[0] for s in sizes[i-4:i])==k4:
                mb+=1 if sizes[i]=="BIG" else 0; ms+=1 if sizes[i]=="SMALL" else 0
        if mb+ms>=4: v(10,mb/(mb+ms),ms/(mb+ms),1.3)
        else: v(10,.5,.5,.4)
    pr=sizes[:30].count("BIG")/min(30,len(sizes)); v(11,pr,1-pr,.9)
    rc=sum(1 for c in colors[:15] if c in ("red","violet_red"))
    if rc>=10: v(12,0,1,.8)
    elif rc>=8: v(12,0,.8,.7)
    elif rc<=5: v(12,1,0,.8)
    elif rc<=7: v(12,.8,0,.7)
    else: v(12,.5,.5,.4)
    if len(nums)>=10:
        diffs=[abs(nums[i]-nums[i+1]) for i in range(9)]
        avg=sum(diffs)/len(diffs); std=math.sqrt(sum((d-avg)**2 for d in diffs)/9)
        if avg>5 or std>2.5: v(13,.5,.5,.5)
        else: v(13,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.8)
    runs=[]; cur=sizes[0]; cnt=1
    for i in range(1,min(len(sizes),25)):
        if sizes[i]==cur: cnt+=1
        else: runs.append(cnt); cur=sizes[i]; cnt=1
    runs.append(cnt); ar=sum(runs)/len(runs)
    if runs[0]>=ar*2.5: v(14,1.8 if sizes[0]=="SMALL" else 0, 1.8 if sizes[0]=="BIG" else 0, 1.2)
    elif runs[0]>=ar*1.5: v(14,1.2 if sizes[0]=="SMALL" else 0, 1.2 if sizes[0]=="BIG" else 0, .9)
    else: v(14,.5,.5,.5)
    try:
        p=int(str(history[0]["period"])[-2:]); v(15,.63 if p%2==0 else .37, .37 if p%2==0 else .63,.7)
    except Exception: v(15,.5,.5,.3)
    if len(nums)>=3:
        nm={}
        for i in range(len(nums)-1):
            nm.setdefault(nums[i],{"B":0,"S":0}); nm[nums[i]]["B" if nums[i+1]>=5 else "S"]+=1
        c=nm.get(nums[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(16,c["B"]/t,c["S"]/t,1.3)
        elif t>=3: v(16,c["B"]/t,c["S"]/t,0.9)
        else: v(16,.5,.5,.4)
    ec=Counter(sizes[:20]); et=sum(ec.values())
    if et>0:
        en=-sum((vv/et)*math.log2(vv/et) for vv in ec.values() if vv)
        if en>0.97: v(17,.5,.5,.3)
        elif en<0.7: v(17,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.9)
        else: v(17,1 if sizes[0]=="SMALL" else 0, 1 if sizes[0]=="BIG" else 0,.7)
    fibs=[1,2,3,5,8,13,21]; fs2=[sizes[f-1] for f in fibs if f<=len(sizes)]
    fb2=fs2.count("BIG"); fs3=fs2.count("SMALL")
    if fb2+fs3>0: v(18,fs3/(fb2+fs3),fb2/(fb2+fs3),.9)
    if len(sizes)>=4:
        tm={}
        for i in range(3,len(sizes)):
            k=sizes[i-3]+sizes[i-2]+sizes[i-1]; tm.setdefault(k,{"B":0,"S":0}); tm[k]["B" if sizes[i]=="BIG" else "S"]+=1
        c=tm.get(sizes[2]+sizes[1]+sizes[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=4: v(19,c["B"]/t,c["S"]/t,1.6)
        elif t>=2: v(19,c["B"]/t,c["S"]/t,1.1)
        else: v(19,.5,.5,.5)
    if len(sizes)>=5:
        qm={}
        for i in range(4,len(sizes)):
            k=sizes[i-4]+sizes[i-3]+sizes[i-2]+sizes[i-1]; qm.setdefault(k,{"B":0,"S":0}); qm[k]["B" if sizes[i]=="BIG" else "S"]+=1
        c=qm.get(sizes[3]+sizes[2]+sizes[1]+sizes[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=3: v(20,c["B"]/t,c["S"]/t,1.4)
        else: v(20,.5,.5,.4)
    r3=sizes[:3].count("BIG"); v(21,1.2 if r3<=1 else 0, 1.2 if r3>=2 else 0,.9)
    r5=sizes[:5].count("BIG"); v(22,1.1 if r5<=2 else (0 if r5>=4 else .5), 1.1 if r5>=3 else (0 if r5<=1 else .5),.8)
    ep=sum(1 for n in nums[:12] if n%2==0); v(23,(12-ep)/12,ep/12,.8)
    if len(nums)>=6:
        s1=sum(nums[:3]); s2=sum(nums[3:6]); diff=s1-s2
        if diff>6: v(24,0,1.2,.8)
        elif diff<-6: v(24,1.2,0,.8)
        elif diff>3: v(24,0,.8,.6)
        elif diff<-3: v(24,.8,0,.6)
        else: v(24,.5,.5,.4)
    alt=sum(1 for i in range(1,min(12,len(sizes))) if sizes[i]!=sizes[i-1])
    ratio=alt/11 if len(sizes)>=12 else alt/max(1,len(sizes)-1)
    if ratio>0.7: v(25,.5,.5,.5)
    elif len(sizes)>1: v(25,.65 if sizes[0]=="SMALL" else .35, .65 if sizes[0]=="BIG" else .35,.7)
    mc=Counter(nums[:20]); mn=mc.most_common(1)[0][0] if mc else 0
    v(26,0 if mn>=5 else 1, 1 if mn>=5 else 0,1.0)
    l10=sizes[:10].count("BIG")
    if l10<=2: v(27,1.4,0,1.1)
    elif l10>=8: v(27,0,1.4,1.1)
    elif l10<=3: v(27,1.1,0,.8)
    elif l10>=7: v(27,0,1.1,.8)
    else: v(27,.5,.5,.5)
    con=0
    for i in range(len(sizes)-1):
        if sizes[i]==sizes[i+1]: con+=1
        else: break
    if con>=4: v(28,1.8 if sizes[0]=="SMALL" else 0, 1.8 if sizes[0]=="BIG" else 0,1.3)
    elif con>=2: v(28,1.2 if sizes[0]=="SMALL" else 0, 1.2 if sizes[0]=="BIG" else 0,.9)
    elif con>=1: v(28,.8 if sizes[0]=="SMALL" else 0, .8 if sizes[0]=="BIG" else 0,.7)
    else: v(28,.5,.5,.5)
    sq=sorted(nums[:20]); q1=sq[4] if len(sq)>5 else 2; q3=sq[14] if len(sq)>15 else 7
    if nums[0]<q1: v(29,1.3,0,.9)
    elif nums[0]>q3: v(29,0,1.3,.9)
    else: v(29,.5,.5,.5)
    if len(nums)>=10:
        sp=max(nums[:10])-min(nums[:10])
        if sp<2: v(30,.9 if sizes[0]=="SMALL" else .1, .9 if sizes[0]=="BIG" else .1,.8)
        elif sp>7: v(30,.5,.5,.4)
        else: v(30,.5,.5,.5)
    if len(sizes)>=6:
        cy3=sum(1 for i in range(min(6,len(sizes)-3)) if sizes[i+3]==sizes[i])
        if cy3>=5: v(31,1.2 if sizes[3]=="BIG" else 0, 1.2 if sizes[3]=="SMALL" else 0,1.1)
        else: v(31,.5,.5,.5)
    if len(sizes)>=10:
        cy5=sum(1 for i in range(min(5,len(sizes)-5)) if sizes[i+5]==sizes[i])
        if cy5>=4: v(32,1.1 if sizes[5]=="BIG" else 0, 1.1 if sizes[5]=="SMALL" else 0,.9)
        else: v(32,.5,.5,.5)
    if len(colors)>=3:
        cm2={}
        for i in range(len(colors)-1):
            cm2.setdefault(colors[i],{"B":0,"S":0})
            cm2[colors[i]]["B" if colors[i+1] in ("red","violet_red") else "S"]+=1
        c=cm2.get(colors[0],{"B":0,"S":0}); t=c["B"]+c["S"]
        if t>=5: v(33,c["B"]/t,c["S"]/t,.9)
        else: v(33,.5,.5,.4)
    total=_wingo_state.get("total_pred",0); correct=_wingo_state.get("correct_pred",0)
    if total>=10:
        acc=correct/total
        if acc<0.40: v(34,ss,sb,.6)
        elif acc>0.65: v(34,sb,ss,.5)
        else: v(34,.5,.5,.3)
    loss_stk=_wingo_state.get("loss_streak",0); win_stk=_wingo_state.get("win_streak",0)
    if loss_stk>=4: v(35,.55 if sb>=ss else .45, .55 if ss>sb else .45, 1.3)
    elif win_stk>=6: v(35,ss*.4,sb*.4,.4)
    else: v(35,.5,.5,.3)

    tw = sb+ss or 1
    pB = round(sb/tw*100); pS = 100-pB
    sig = "BIG" if sb>=ss else "SMALL"
    conf = max(pB,pS)

    cs={"red":0.0,"green":0.0,"violet":0.0}
    for i,col in enumerate(colors[:25]):
        w=1/(i+1)
        if col=="red": cs["red"]+=w
        elif col=="green": cs["green"]+=w
        else: cs["violet"]+=w*1.7
    if sig=="BIG": cs["red"]+=3.0; cs["violet"]+=1.0
    else: cs["green"]+=3.0; cs["violet"]+=1.0
    ct=sum(cs.values()) or 1
    pR=round(cs["red"]/ct*100); pG=round(cs["green"]/ct*100); pV=max(0,100-pR-pG)
    tc="red" if pR>pG and pR>pV else ("green" if pG>pR and pG>pV else "violet")

    ns=[0.0]*10
    for i,n in enumerate(nums[:35]): ns[n]+=1/(i*.08+1)
    for n in range(10):
        if _w_sizeof(n)==sig: ns[n]+=4
    ranked=sorted(range(10),key=lambda x:-ns[x])

    if conf>=80: conf_label="🔥 ULTRA HIGH"
    elif conf>=70: conf_label="💪 HIGH"
    elif conf>=60: conf_label="✅ MEDIUM"
    else: conf_label="⚠️ LOW"

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
# MENUS
# ════════════════════════════════════════════
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📥  ভিডিও ডাউনলোড", callback_data="dl_help")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("✨  Enhance ULTRA", callback_data="enhance_help"),
         InlineKeyboardButton("📱  TikTok Mode", callback_data="tt_help")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🎯  WinGo Prediction", callback_data="wingo_menu")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
    ])

def wingo_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡  এখনই Prediction!", callback_data="wingo_predict")],
        [InlineKeyboardButton("🔄  Auto ON (৩০s)", callback_data="wingo_auto_on"),
         InlineKeyboardButton("⏹  Auto OFF", callback_data="wingo_auto_off")],
        [InlineKeyboardButton("📊  Stats", callback_data="wingo_stats"),
         InlineKeyboardButton("🔙  Back", callback_data="back_main")],
    ])

def edit_btns(job):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 TikTok Mode", callback_data=f"do_tt_mode_{job}"),
         InlineKeyboardButton("✨ Enhance", callback_data=f"do_enhance_{job}")],
        [InlineKeyboardButton("🎯 WinGo", callback_data="wingo_predict")],
    ])

START_TEXT = """
🎬 *Video Bot {ver}*

━━━━━━━━━━━━━━━━━━━━━━
📥 *Download*
  YouTube · TikTok · Instagram
  Facebook · Pinterest

📱 *TikTok Mode*
  ❌ Copyright bypass
  ❌ Eligible For You bypass
  7-layer processing

✨ *Enhance ULTRA*
  Cinematic quality upgrade

🎯 *WinGo ULTRA*
  35-layer AI prediction
━━━━━━━━━━━━━━━━━━━━━━

👇 *Link পাঠান* → Download
👇 *ভিডিও পাঠান* → Edit
""".strip()

# ════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════
async def cmd_start(u, c):
    name = md_escape(u.effective_user.first_name or "বন্ধু")
    await safe_reply(u.message,
        START_TEXT.format(ver=VERSION) + f"\n\n👤 স্বাগতম *{name}*!",
        parse_mode="Markdown", reply_markup=main_menu())

async def cmd_wingo(u, c):
    await safe_reply(u.message,
        "🎯 *WinGo ULTRA — 35-Layer AI*\n\n👇",
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
            f"⏳ *{plat} ডাউনলোড হচ্ছে...*\nঅপেক্ষা করুন ⌛",
            parse_mode="Markdown")
        await msg.chat.send_action(ChatAction.UPLOAD_VIDEO)

        loop = asyncio.get_running_loop()
        ok, title, err, filepath = await loop.run_in_executor(executor, yt_dl, url, job)

        if not ok:
            await safe_edit(st,
                f"❌ *ডাউনলোড ব্যর্থ!*\n\n`{err[:200]}`\n\n💡 অন্য link try করুন।",
                parse_mode="Markdown"); return

        size_mb = Path(filepath).stat().st_size / 1024 / 1024
        await safe_edit(st, f"⏫ *আপলোড হচ্ছে...* `{size_mb:.1f} MB`", parse_mode="Markdown")

        try:
            with open(filepath,"rb") as f:
                await msg.reply_video(f,
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
            await safe_edit(st, f"❌ আপলোড ব্যর্থ: `{e}`", parse_mode="Markdown")
        return

    if msg.video or msg.document:
        file_obj = msg.video or msg.document
        job = uuid.uuid4().hex[:12]
        _user_state[uid] = {"job":job,"file_id":file_obj.file_id}
        await safe_reply(msg,
            "📥 *ভিডিও পেয়েছি!*\n\n👇 কী করতে চান?",
            parse_mode="Markdown", reply_markup=edit_btns(job))
        return

    await safe_reply(msg,
        "📥 *Link পাঠান* → Download\n"
        "🎬 *ভিডিও পাঠান* → Edit\n\n"
        "/start — Main menu\n/wingo — WinGo Prediction")

async def handle_cb(u, c):
    q = u.callback_query
    try: await q.answer()
    except Exception: pass
    uid  = q.from_user.id
    data = q.data

    if data == "noop": return

    if data == "back_main":
        await safe_edit(q.message, START_TEXT.format(ver=VERSION),
                        parse_mode="Markdown", reply_markup=main_menu()); return

    if data == "wingo_menu":
        await safe_edit(q.message,
            "🎯 *WinGo ULTRA*\n35-layer AI prediction!\n\n👇",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data in ("dl_help","enhance_help","tt_help"):
        hints = {
            "dl_help":    "📥 YouTube/TikTok/Instagram/Facebook/Pinterest link পাঠান!",
            "enhance_help": "✨ ভিডিও পাঠান — Enhance ULTRA করব!",
            "tt_help":    "📱 ভিডিও পাঠান → TikTok Mode (Copyright + Eligible bypass)!",
        }
        await q.message.reply_text(hints[data]); return

    if data == "wingo_predict":
        await safe_edit(q.message,
            "⏳ *WinGo ULTRA — data আনছি...*\n35 layers analyzing ⚡",
            parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        history = await loop.run_in_executor(executor, _w_fetch)
        if not history:
            await safe_edit(q.message,
                "❌ *WinGo API সংযোগ ব্যর্থ!*\n\n"
                "সার্ভার এখন বন্ধ থাকতে পারে।\n"
                "কিছুক্ষণ পর আবার চেষ্টা করুন।",
                parse_mode="Markdown", reply_markup=wingo_menu()); return
        pred = await loop.run_in_executor(executor, _w_analyze, history)
        if not pred:
            await safe_edit(q.message,"❌ Analysis ব্যর্থ!",
                            reply_markup=wingo_menu()); return

        _wingo_state["history"]     = history
        _wingo_state["last_period"] = pred["period"]

        se = "🔺" if pred["sig"]=="BIG" else "🔻"
        te = {"red":"🔴","green":"🟢","violet":"🟣"}.get(pred["tc"],"⚪")
        sig_bn = "বড় (৫-৯)" if pred["sig"]=="BIG" else "ছোট (০-৪)"
        bar_len = 10; filled = round(pred["conf"]/100*bar_len)
        bar = "█"*filled + "░"*(bar_len-filled)

        txt = (
            f"🎯 *WinGo ULTRA — 35 Layer*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{se} *{pred['sig']}* — _{sig_bn}_\n"
            f"📊 `{bar}` `{pred['conf']}%`\n"
            f"🔥 *{pred['conf_label']}*\n\n"
            f"🔴 BIG `{pred['pB']}%` | SMALL `{pred['pS']}%` 🟢\n\n"
            f"🎨 *Color:*\n"
            f"  {te} *{pred['tc'].upper()}*\n"
            f"  🔴`{pred['pR']}%` 🟢`{pred['pG']}%` 🟣`{pred['pV']}%`\n\n"
            f"🎲 *Number:*\n"
            f"  ★ TOP: `{pred['numTop']}`\n"
            f"  Backup: `{pred['numAlt'][0]}` `{pred['numAlt'][1]}` `{pred['numAlt'][2]}` `{pred['numAlt'][3]}`\n\n"
            f"🧠 *Layers:* BIG `{pred['big_layers']}` | SMALL `{pred['small_layers']}` / `{pred['total_layers']}`\n\n"
            f"📅 Period: `{pred['period'][-6:] if pred['period'] else '—'}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Pattern analysis মাত্র_"
        )
        await safe_edit(q.message, txt, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 আবার দেখুন", callback_data="wingo_predict")],
                            [InlineKeyboardButton("📊 Stats", callback_data="wingo_stats"),
                             InlineKeyboardButton("🔙 Menu", callback_data="wingo_menu")],
                        ])); return

    if data == "wingo_auto_on":
        _wingo_subs.add(uid)
        await safe_edit(q.message,
            "✅ *Auto Prediction চালু!*\nপ্রতি নতুন period এ আসবে।",
            parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_auto_off":
        _wingo_subs.discard(uid)
        await safe_edit(q.message, "⏹ *Auto Prediction বন্ধ।*",
                        parse_mode="Markdown", reply_markup=wingo_menu()); return

    if data == "wingo_stats":
        hist = _wingo_state.get("history",[])[:10]
        total = _wingo_state.get("total_pred",0)
        correct = _wingo_state.get("correct_pred",0)
        acc = round(correct/total*100) if total else 0
        hist_items = []
        for h in hist:
            sz_e = "🔴" if h["size"]=="BIG" else "🟢"
            hist_items.append(f"{sz_e}`{h['number']}`")
        hist_txt = " ".join(hist_items) if hist_items else "—"
        await safe_edit(q.message,
            f"📊 *WinGo Stats*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎯 Total: `{total}` | ✅ Acc: `{acc}%`\n"
            f"🔥 Win streak: `{_wingo_state.get('win_streak',0)}`\n"
            f"💀 Loss streak: `{_wingo_state.get('loss_streak',0)}`\n"
            f"👥 Auto subs: `{len(_wingo_subs)}`\n\n"
            f"🕹️ Last 10:\n{hist_txt}",
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
        f"⚙️ *{label} প্রসেস হচ্ছে...*\n\nঅপেক্ষা করুন ⏳",
        parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    out_path, err = await loop.run_in_executor(executor, PROCESSORS[mode], inp_path)

    if not out_path:
        await safe_edit(q.message,
            f"❌ *Processing ব্যর্থ!*\n\n`{err[:300]}`\n\n💡 ছোট ভিডিও দিয়ে চেষ্টা করুন।",
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
                    result_emoji = "❌ LOSS"

                acc = round(_wingo_state["correct_pred"] / _wingo_state["total_pred"] * 100)
                se_p = "🔺" if pred_sig=="BIG" else "🔻"
                se_a = "🔺" if actual_size=="BIG" else "🔻"
                te_a = {"red":"🔴","green":"🟢","violet":"🟣"}.get(actual_color,"⚪")

                result_txt = (
                    f"📊 *Result — Period {pending['period'][-6:]}*\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"🎯 Prediction:  {se_p} *{pred_sig}*\n"
                    f"✔️ Actual:      {se_a} *{actual_size}* | {te_a} `{actual_color.upper()}` | 🎲 `{actual_num}`\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"{'✅ *WIN!* 🎉' if size_correct else '❌ *LOSS*'}\n"
                    f"📈 Accuracy: `{acc}%` ({_wingo_state['correct_pred']}/{_wingo_state['total_pred']})\n"
                    f"━━━━━━━━━━━━━━━━"
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
        bar = "█"*round(pred["conf"]/10) + "░"*(10-round(pred["conf"]/10))
        sig_bn = "বড় (৫-৯)" if pred["sig"]=="BIG" else "ছোট (০-৪)"

        pred_txt = (
            f"🎯 *WinGo Prediction*\n"
            f"📅 Period: `{latest_period[-6:]}`\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{se} *{pred['sig']}* — _{sig_bn}_\n"
            f"📊 `{bar}` `{pred['conf']}%` {pred['conf_label']}\n"
            f"{te} Color: *{pred['tc'].upper()}*\n"
            f"🎲 Number: ★`{pred['numTop']}` | backup: `{'` `'.join(str(x) for x in pred['numAlt'])}`\n"
            f"🧠 BIG:{pred['big_layers']} SMALL:{pred['small_layers']}/35\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏳ _৩০ সেকেন্ড পর result আসবে..._"
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
