#!/usr/bin/env python3
"""EnduraIQ Coach v3 — Professional endurance coaching intelligence"""

import os
import csv
import io
import re
from datetime import datetime
from collections import defaultdict
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN", "8744873375:AAFg9AGD4FK_ulE4zR3lb6O4cnK6P2Vl5-8")

user_profiles = {}
user_workouts = defaultdict(list)

def safe_int(val):
    try: return int(str(val).strip().strip('"').replace(',', ''))
    except: return 0

def safe_float(val):
    try: return float(str(val).strip().strip('"').replace(',', ''))
    except: return 0.0

def pace_to_min(p):
    try:
        parts = str(p).strip().strip('"').split(':')
        if len(parts) == 2: return int(parts[0]) + float(parts[1])/60
        return 0
    except: return 0

def get_zones(lthr):
    return {
        'Z1': (0, int(lthr * 0.81)),
        'Z2': (int(lthr * 0.81), int(lthr * 0.90)),
        'Z3': (int(lthr * 0.90), int(lthr * 0.94)),
        'Z4': (int(lthr * 0.94), int(lthr * 1.0)),
        'Z5': (int(lthr * 1.0), 999),
    }

def classify(hr, zones):
    for name, (lo, hi) in zones.items():
        if lo <= hr < hi: return name
    return 'Z5'

def detect_activity(text):
    first = text.split('\n')[0].lower()
    if 'swim stroke' in first or 'swolf' in first or 'lengths' in first: return 'swim'
    if 'avg speed' in first and 'avg pace' not in first: return 'bike'
    return 'run'

def progress_bar(pct, width=15):
    filled = int(pct * width / 100)
    return "█" * filled + "░" * (width - filled)

def zone_dist(hrs, zones):
    counts = {k: 0 for k in zones}
    for hr in hrs:
        counts[classify(hr, zones)] += 1
    total = len(hrs)
    return {k: (v, v*100//total if total else 0) for k, v in counts.items()}

def cardiac_drift(laps):
    if len(laps) > 5: analysis = laps[1:-2]
    elif len(laps) > 3: analysis = laps[1:]
    else: analysis = laps
    if len(analysis) < 2: return 0, 0, 0
    mid = len(analysis) // 2
    first = sum(l['hr'] for l in analysis[:mid]) / mid
    second = sum(l['hr'] for l in analysis[mid:]) / len(analysis[mid:])
    drift = ((second - first) / first) * 100
    return first, second, drift

# ── PARSERS ──────────────────────────────────────────────
def parse_run(text):
    r = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    h = next(r)
    idx = {'hr': None, 'pace': None, 'dist': None, 'time': None, 'cad': None}
    for i, col in enumerate(h):
        c = col.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in c: idx['hr'] = i
        if 'avg pace' in c and idx['pace'] is None: idx['pace'] = i
        if 'distance' in c and idx['dist'] is None: idx['dist'] = i
        if 'cumulative time' in c: idx['time'] = i
        if 'avg run cadence' in c: idx['cad'] = i
    if idx['hr'] is None: return None
    laps, summary = [], None
    for row in r:
        if not row: continue
        label = row[0].strip().strip('"')
        if label.lower() == 'summary':
            summary = {
                'avg_hr': safe_int(row[idx['hr']]),
                'time': row[idx['time']].strip().strip('"') if idx['time'] else '',
                'distance': safe_float(row[idx['dist']]) if idx['dist'] else 0,
                'avg_pace': row[idx['pace']].strip().strip('"') if idx['pace'] else '',
                'avg_cad': safe_int(row[idx['cad']]) if idx['cad'] else 0,
            }
            continue
        hr = safe_int(row[idx['hr']])
        if hr > 0:
            lap = {'lap': label, 'hr': hr}
            if idx['pace'] and idx['pace'] < len(row):
                lap['pace'] = row[idx['pace']].strip().strip('"')
                lap['pace_min'] = pace_to_min(lap['pace'])
            if idx['cad'] and idx['cad'] < len(row): lap['cad'] = safe_int(row[idx['cad']])
            laps.append(lap)
    return {'laps': laps, 'summary': summary}

def parse_bike(text):
    r = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    h = next(r)
    idx = {'hr': None, 'speed': None, 'dist': None, 'time': None}
    for i, col in enumerate(h):
        c = col.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in c: idx['hr'] = i
        if 'avg speed' in c and idx['speed'] is None: idx['speed'] = i
        if 'distance' in c and idx['dist'] is None: idx['dist'] = i
        if 'cumulative time' in c: idx['time'] = i
    if idx['hr'] is None: return None
    laps, summary = [], None
    for row in r:
        if not row: continue
        label = row[0].strip().strip('"')
        if label.lower() == 'summary':
            summary = {
                'avg_hr': safe_int(row[idx['hr']]),
                'time': row[idx['time']].strip().strip('"') if idx['time'] else '',
                'distance': safe_float(row[idx['dist']]) if idx['dist'] else 0,
                'avg_speed': safe_float(row[idx['speed']]) if idx['speed'] else 0,
            }
            continue
        hr = safe_int(row[idx['hr']])
        if hr > 0:
            lap = {'lap': label, 'hr': hr}
            if idx['speed'] and idx['speed'] < len(row): lap['speed'] = safe_float(row[idx['speed']])
            laps.append(lap)
    return {'laps': laps, 'summary': summary}

def parse_swim(text):
    r = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    h = next(r)
    idx = {'hr': None, 'pace': None, 'swolf': None, 'dist': None, 'stroke': None}
    for i, col in enumerate(h):
        c = col.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in c: idx['hr'] = i
        if 'avg pace' in c: idx['pace'] = i
        if 'swolf' in c: idx['swolf'] = i
        if 'distance' in c: idx['dist'] = i
        if 'swim stroke' in c: idx['stroke'] = i
    if idx['hr'] is None: return None
    sets, summary = [], None
    for row in r:
        if not row: continue
        label = row[1].strip().strip('"') if len(row) > 1 else ''
        if label.lower() == 'summary':
            summary = {'avg_hr': safe_int(row[idx['hr']]) if idx['hr'] else 0}
            continue
        if idx['stroke'] and idx['stroke'] < len(row):
            if row[idx['stroke']].strip().strip('"').lower() in ('rest', '--'): continue
        if '.' in label: continue
        hr = safe_int(row[idx['hr']]) if idx['hr'] and idx['hr'] < len(row) else 0
        if hr > 0 and label:
            s = {'set': label, 'hr': hr}
            if idx['pace'] and idx['pace'] < len(row):
                s['pace'] = row[idx['pace']].strip().strip('"')
                s['pace_min'] = pace_to_min(s['pace'])
            if idx['swolf'] and idx['swolf'] < len(row): s['swolf'] = safe_int(row[idx['swolf']])
            sets.append(s)
    return {'sets': sets, 'summary': summary}

def classify_run_type(pct):
    if pct < 75: return "Recovery Run", "🟢"
    if pct < 85: return "Easy / Zone 2", "🟢"
    if pct < 91: return "Aerobic", "🔵"
    if pct < 96: return "Tempo", "🟡"
    if pct < 101: return "Threshold", "🟠"
    return "VO2max / Intervals", "🔴"

def classify_ride_type(pct):
    if pct < 75: return "Recovery", "🟢"
    if pct < 85: return "Zone 2 Endurance", "🟢"
    if pct < 91: return "Aerobic", "🔵"
    if pct < 96: return "Sweet Spot / Tempo", "🟡"
    if pct < 101: return "Threshold", "🟠"
    return "VO2max", "🔴"

# ── ANALYSIS ─────────────────────────────────────────────
def analyze_run(data, lthr, uid):
    laps, summary = data['laps'], data.get('summary') or {}
    if len(laps) < 3: return "Not enough laps."
    zones = get_zones(lthr)
    avg_hr = summary.get('avg_hr') or sum(l['hr'] for l in laps) // len(laps)
    pct = avg_hr / lthr * 100
    run_type, emoji = classify_run_type(pct)
    dist = summary.get('distance', 0)
    time = summary.get('time', 'N/A')
    cad = summary.get('avg_cad', 0)
    
    zd = zone_dist([l['hr'] for l in laps], zones)
    first, second, drift = cardiac_drift(laps)
    
    msg = f"""{emoji} *RUN ANALYSIS*
━━━━━━━━━━━━━━━━━━━━
📍 {dist:.2f} km · ⏱ {time} · 💓 {avg_hr} bpm

*Type:* {run_type}
_{pct:.0f}% of LTHR ({lthr})_

*Zones:*"""
    labels = {'Z1': 'Recovery', 'Z2': 'Aerobic', 'Z3': 'Tempo', 'Z4': 'Threshold', 'Z5': 'VO2max'}
    for z, (c, p) in zd.items():
        if c > 0 or z in ('Z1','Z2','Z3'):
            msg += f"\n{z} {labels[z]:10} {progress_bar(p)} {p:>3}%"
    
    msg += f"\n\n*Cardiac Drift:*\n{first:.0f} → {second:.0f} bpm ({drift:+.1f}%)"
    if drift < 3: msg += "\n✅ Excellent aerobic fitness"
    elif drift < 5: msg += "\n✅ Solid aerobic base"
    elif drift < 8: msg += "\n⚠️ Moderate — need more Zone 2"
    else: msg += "\n🔴 High — aerobic engine needs work"
    
    if cad:
        if cad >= 175: msg += f"\n\n👟 Cadence: {cad} spm ✅"
        elif cad >= 170: msg += f"\n\n👟 Cadence: {cad} spm (aim for 175+)"
        else: msg += f"\n\n👟 Cadence: {cad} spm ⚠️ (low — longer strides waste energy)"
    
    msg += "\n\n*💡 Coach's Read:*"
    z2_ceil = zones['Z2'][1]
    if pct < 85:
        over = sum(1 for l in laps if l['hr'] > z2_ceil)
        if over >= 3:
            msg += f"\nYou went above Zone 2 ({z2_ceil} bpm) on {over} laps. This is the #1 amateur mistake — easy runs that aren't easy. Slow down 20-30 sec/km. Aerobic gains come from easy effort, not moderate effort."
        elif drift > 8:
            msg += f"\nHigh drift on an easy run = weak aerobic base. The fix is MORE easy running, not less. Your heart is working hard because your cardiovascular system is underdeveloped."
        else:
            msg += f"\nTextbook Zone 2. This is where base fitness is built. Boring but effective."
    elif pct < 91:
        msg += f"\nAerobic sweet spot. Good stimulus. Just ensure 80% of your weekly volume stays below Zone 2 ceiling ({z2_ceil})."
    elif pct < 96:
        msg += f"\nTempo session. 'Comfortably uncomfortable.' Keep to 1-2x per week. Next 2 days should be easy or rest."
    elif pct < 101:
        msg += f"\nThreshold work — race pace territory. Directly builds your lactate threshold, the #1 predictor of endurance performance."
    else:
        msg += f"\nHigh intensity. Major stimulus. Body needs 48-72h to adapt — don't stack another hard day."
    
    user_workouts[uid].append({
        'date': datetime.now(), 'sport': 'run',
        'avg_hr': avg_hr, 'distance': dist,
        'type': run_type, 'drift': drift, 'pct_lthr': pct,
    })
    return msg

def analyze_bike(data, lthr, uid):
    laps, summary = data['laps'], data.get('summary') or {}
    if len(laps) < 2: return "Not enough laps."
    zones = get_zones(lthr)
    avg_hr = summary.get('avg_hr') or sum(l['hr'] for l in laps) // len(laps)
    avg_speed = summary.get('avg_speed', 0)
    dist = summary.get('distance', 0)
    time = summary.get('time', 'N/A')
    pct = avg_hr / lthr * 100
    ride_type, emoji = classify_ride_type(pct)
    
    zd = zone_dist([l['hr'] for l in laps], zones)
    first, second, drift = cardiac_drift(laps)
    
    msg = f"""{emoji} *BIKE ANALYSIS*
━━━━━━━━━━━━━━━━━━━━
📍 {dist:.1f} km · ⏱ {time} · 💓 {avg_hr} bpm"""
    if avg_speed: msg += f" · {avg_speed:.1f} km/h"
    msg += f"\n\n*Type:* {ride_type}\n_{pct:.0f}% of LTHR ({lthr})_\n\n*Zones:*"
    
    labels = {'Z1': 'Recovery', 'Z2': 'Endurance', 'Z3': 'Sweet Spot', 'Z4': 'Threshold', 'Z5': 'VO2max'}
    for z, (c, p) in zd.items():
        if c > 0 or z in ('Z1','Z2','Z3'):
            msg += f"\n{z} {labels[z]:12} {progress_bar(p)} {p:>3}%"
    
    msg += f"\n\n*Cardiac Drift:*\n{first:.0f} → {second:.0f} bpm ({drift:+.1f}%)"
    if drift < 0: msg += "\n✅ HR decreased — excellent efficiency"
    elif drift < 3: msg += "\n✅ Minimal drift — solid pacing"
    elif drift < 6: msg += "\n⚠️ Moderate drift"
    else: msg += "\n🔴 Significant drift — pacing needs work"
    
    if avg_speed > 0:
        t = 180 / avg_speed
        h, m = int(t), int((t % 1) * 60)
        msg += f"\n\n🏁 *Ironman 180km Projection:*\nAt {avg_speed:.1f} km/h: ~{h}h {m:02d}min"
    
    msg += "\n\n*💡 Coach's Read:*"
    z2_ceil = zones['Z2'][1]
    z3_floor = zones['Z3'][0]
    over = sum(1 for l in laps if l['hr'] >= z3_floor)
    if pct < 85:
        msg += f"\nTextbook Zone 2 riding. This IS the foundation for long-course success. Ironman bike should look exactly like this — consistent effort, nothing heroic."
    elif pct < 91 and over >= len(laps) // 3:
        msg += f"\nYou crept above Zone 2 on {over} laps. For Ironman training this is too hard — leaves you unable to run off the bike. Slow down early, finish strong."
    elif pct < 96:
        msg += f"\nSweet spot work. Great for 70.3/Olympic training. Too hard for Ironman race pace."
    else:
        msg += f"\nHard ride. Builds threshold power but costs recovery. Tomorrow must be easy or off."
    
    user_workouts[uid].append({
        'date': datetime.now(), 'sport': 'bike',
        'avg_hr': avg_hr, 'distance': dist, 'avg_speed': avg_speed,
        'type': ride_type, 'drift': drift, 'pct_lthr': pct,
    })
    return msg

def analyze_swim(data, uid):
    sets = [s for s in data['sets'] if s['hr'] > 50]
    if len(sets) < 2: return "Not enough sets with HR."
    
    msg = "🏊 *SWIM ANALYSIS*\n━━━━━━━━━━━━━━━━━━━━\n\n*Sets:*"
    for s in sets[:10]:
        line = f"\nSet {s['set']}: {s['hr']} bpm"
        if 'pace' in s and s.get('pace') and s['pace'] != '--': line += f" · {s['pace']}/100m"
        if s.get('swolf', 0) > 0: line += f" · SWOLF {s['swolf']}"
        msg += line
    
    drift = ((sets[-1]['hr'] - sets[0]['hr']) / sets[0]['hr']) * 100
    msg += f"\n\n*Cardiac Drift:*\n{sets[0]['hr']} → {sets[-1]['hr']} bpm ({drift:+.1f}%)"
    if drift > 15: msg += "\n🔴 High — aerobic swim base is limiter"
    elif drift > 8: msg += "\n⚠️ Moderate — more continuous volume"
    else: msg += "\n✅ Controlled"
    
    swolf_sets = [s for s in sets if s.get('swolf', 0) > 0]
    if len(swolf_sets) >= 2:
        sc = swolf_sets[-1]['swolf'] - swolf_sets[0]['swolf']
        msg += f"\n\n*Technique:* SWOLF {swolf_sets[0]['swolf']} → {swolf_sets[-1]['swolf']} ({sc:+d})"
        if sc > 4: msg += "\n⚠️ Technique breaking down — add drill work"
        elif sc > 0: msg += "\nSlight degradation — normal"
        else: msg += "\n✅ Maintained"
    
    pace_sets = [s for s in sets if s.get('pace_min', 0) > 0]
    if len(pace_sets) >= 3:
        decay = ((pace_sets[-1]['pace_min'] - pace_sets[0]['pace_min']) / pace_sets[0]['pace_min']) * 100
        msg += f"\n\n*Pace Stability:*\n{pace_sets[0]['pace']} → {pace_sets[-1]['pace']}"
        if decay < 3: msg += f"\n✅ Held pace ({decay:+.1f}%)"
        elif decay < 8: msg += f"\n⚠️ Pace dropped {decay:.0f}%"
        else: msg += f"\n🔴 Pace dropped {decay:.0f}% — aerobic base weak"
    
    msg += "\n\n*💡 Coach's Read:*"
    if drift > 15:
        msg += "\nThe HR jump is the biggest signal. Your aerobic swim base is underdeveloped — normal for triathletes coming from run/bike. Fix: 2-3x/week continuous 800-1500m swims at easy pace. Goal isn't to get tired — it's to teach your aerobic system to swim."
    elif drift > 8:
        msg += "\nAdd more continuous work. Short intervals = anaerobic. Long continuous = aerobic base (what Ironman needs)."
    else:
        msg += "\nStrong aerobic swim fitness. You can push pace and volume now."
    
    user_workouts[uid].append({
        'date': datetime.now(), 'sport': 'swim',
        'avg_hr': sum(s['hr'] for s in sets) // len(sets),
        'drift': drift,
    })
    return msg

# ── TRENDS ───────────────────────────────────────────────
def trends(uid):
    w = user_workouts.get(uid, [])
    if len(w) < 3:
        return f"📊 *TREND ANALYSIS*\n\nYou have {len(w)} workout(s) logged. I need at least 3 to show patterns.\n\nSend more Garmin CSVs and I'll show you:\n• HR drift trends over time\n• Sport distribution\n• Whether you're following 80/20\n• Fitness direction (improving/plateauing/declining)"
    
    recent = sorted(w, key=lambda x: x['date'])[-20:]
    
    sport_ct = defaultdict(int)
    for x in recent: sport_ct[x['sport']] += 1
    
    msg = f"📊 *TREND ANALYSIS*\n━━━━━━━━━━━━━━━━━━━━\nLast {len(recent)} workouts\n\n*Sport Distribution:*"
    total = sum(sport_ct.values())
    for sp, c in sport_ct.items():
        emoji = {'run':'🏃','bike':'🚴','swim':'🏊'}.get(sp, '⚡')
        msg += f"\n{emoji} {sp.title()}: {c} ({c*100//total}%)"
    
    runs = [x for x in recent if x['sport'] == 'run']
    if len(runs) >= 2:
        avg_drift = sum(r['drift'] for r in runs) / len(runs)
        msg += f"\n\n*Avg Run Cardiac Drift:* {avg_drift:.1f}%"
        if avg_drift < 5: msg += " ✅"
        elif avg_drift < 8: msg += " ⚠️"
        else: msg += " 🔴"
    
    # 80/20 check
    land = [x for x in recent if x['sport'] in ('run','bike') and 'pct_lthr' in x]
    if len(land) >= 3:
        easy = sum(1 for x in land if x['pct_lthr'] < 85)
        hard = sum(1 for x in land if x['pct_lthr'] >= 91)
        ep = easy * 100 // len(land)
        msg += f"\n\n*Training Intensity:*\n🟢 Easy/Z2: {ep}%\n🟠 Tempo+: {hard * 100 // len(land)}%"
        if ep >= 75: msg += "\n✅ Following 80/20 principle"
        elif ep >= 60: msg += "\n⚠️ Too much moderate ('gray zone')"
        else: msg += "\n🔴 Too much high intensity"
    
    return msg

# ── BOT ──────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """👋 *Welcome to EnduraIQ*

Professional AI coaching for endurance athletes.

I analyze your Garmin workouts using the same sports science elite coaches use — translated into plain language you can act on.

*Quick setup:*

1️⃣ Set your zones:
`run: 180 bike: 165`

2️⃣ Export from Garmin Connect and send me the CSV file

I respond instantly with:
• Workout type classification
• Cardiac drift (are you truly getting fitter?)
• Zone distribution (right intensity?)
• Personalized coaching notes
• Race projections

*Commands:*
/setup — Set LTHR
/defaults — Use estimates
/help — Export from Garmin
/trends — Training patterns
/about — The science I use

_No fluff. No "nice run!" Just signal, not noise._"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """⚙️ *Setup Your Zones*

Send me your LTHR:
`run: 180 bike: 165`

*30-min field test to find LTHR:*
1. Warm up 15 min
2. 30-min solo time trial at hardest sustainable effort
3. Your avg HR for the LAST 20 min ≈ your LTHR
4. Test run and bike separately (they differ ~10 bpm)

*Why LTHR zones matter:*
Max HR or age-based zones are often 10-15 bpm off. LTHR zones are personal to YOUR physiology — what Friel and elite coaches use.

Or use /defaults to start immediately with estimates."""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def defaults_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_profiles[uid] = {'run_lthr': 170, 'bike_lthr': 165}
    msg = """✅ *Defaults Set*
Run LTHR: 170 · Bike LTHR: 165

These are estimates. For real zones, do a 30-min test and update:
`run: YOUR_NUMBER bike: YOUR_NUMBER`

Send me a Garmin CSV to analyze!"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """📖 *How to Export from Garmin*

*On your computer:*
1. connect.garmin.com
2. Click *Activities*
3. Click any workout
4. Click ⚙️ gear icon (top right)
5. Click *Export to CSV*
6. Send the file here

*What I analyze:*
• Run: pace, HR, cadence, zones, drift
• Bike: speed, HR, zones, drift
• Swim: pace, HR, SWOLF, drift"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """🧠 *What EnduraIQ Does*
━━━━━━━━━━━━━━━━━━━━

*The problem:*
Strava, Garmin, TrainingPeaks show you charts. They don't tell you what to DO.

*What I do:*
I analyze your workout and give you an actual coaching read. In plain language.

*The science:*

🔹 *Cardiac Drift* — HR creep at same pace. The best marker of aerobic fitness.

🔹 *LTHR Zones* (Friel) — Zones from YOUR lactate threshold, not age formulas. 10-15 bpm more accurate.

🔹 *Zone Distribution* — Are you really 80/20? Most amateurs are 50/50 ('gray zone').

🔹 *Intensity Classification* — Was it easy, aerobic, tempo, threshold, or VO2? Calculated from YOUR LTHR.

*I'm not:*
A workout generator. A plan app. A social feed.

I'm the coach's eye on your data.

*Pricing:* Free during beta. $15/mo at launch.

_Built by an endurance athlete training for IRONMAN Jacksonville._"""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def trends_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(trends(uid), parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip().lower()
    if 'run:' in text or 'bike:' in text:
        if uid not in user_profiles: user_profiles[uid] = {}
        rm = re.search(r'run:\s*(\d+)', text)
        bm = re.search(r'bike:\s*(\d+)', text)
        if rm: user_profiles[uid]['run_lthr'] = int(rm.group(1))
        if bm: user_profiles[uid]['bike_lthr'] = int(bm.group(1))
        run_lthr = user_profiles[uid].get('run_lthr', 170)
        bike_lthr = user_profiles[uid].get('bike_lthr', 165)
        rz = get_zones(run_lthr)
        bz = get_zones(bike_lthr)
        msg = f"""✅ *Profile Set*

*Run (LTHR {run_lthr}):*
Z1 Recovery: <{rz['Z1'][1]}
Z2 Aerobic: {rz['Z2'][0]}-{rz['Z2'][1]}
Z3 Tempo: {rz['Z3'][0]}-{rz['Z3'][1]}
Z4 Threshold: {rz['Z4'][0]}-{rz['Z4'][1]}
Z5 VO2max: >{rz['Z5'][0]}

*Bike (LTHR {bike_lthr}):*
Z1 Recovery: <{bz['Z1'][1]}
Z2 Endurance: {bz['Z2'][0]}-{bz['Z2'][1]}
Z3 Sweet Spot: {bz['Z3'][0]}-{bz['Z3'][1]}
Z4 Threshold: {bz['Z4'][0]}-{bz['Z4'][1]}
Z5 VO2max: >{bz['Z5'][0]}

Now send me a Garmin CSV!"""
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    await update.message.reply_text("Send me a Garmin CSV file.\n\n/help · /setup · /about · /trends", parse_mode="Markdown")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    profile = user_profiles.get(uid, {'run_lthr': 170, 'bike_lthr': 165})
    doc = update.message.document
    if not doc.file_name.endswith('.csv'):
        await update.message.reply_text("Please send a .csv from Garmin Connect. /help for instructions.")
        return
    await update.message.reply_text("🔄 Analyzing...")
    try:
        f = await doc.get_file()
        b = await f.download_as_bytearray()
        text = b.decode('utf-8', errors='ignore')
        atype = detect_activity(text)
        if atype == 'swim':
            d = parse_swim(text)
            msg = analyze_swim(d, uid) if d and len(d['sets']) >= 2 else "Couldn't parse swim data."
        elif atype == 'bike':
            d = parse_bike(text)
            msg = analyze_bike(d, profile.get('bike_lthr', 165), uid) if d and len(d['laps']) >= 2 else "Couldn't parse bike data."
        else:
            d = parse_run(text)
            msg = analyze_run(d, profile.get('run_lthr', 170), uid) if d and len(d['laps']) >= 2 else "Couldn't parse run data."
        await update.message.reply_text(msg, parse_mode="Markdown")
        if len(user_workouts[uid]) == 3:
            await update.message.reply_text("📊 3 workouts logged — try /trends to see your patterns.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)[:100]}")

async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Welcome & setup"),
        BotCommand("setup", "Set your LTHR zones"),
        BotCommand("defaults", "Use estimated zones"),
        BotCommand("help", "Export from Garmin"),
        BotCommand("trends", "Training patterns"),
        BotCommand("about", "The science I use"),
    ])

def main():
    app = Application.builder().token(TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("defaults", defaults_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("trends", trends_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("EnduraIQ v3 running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
