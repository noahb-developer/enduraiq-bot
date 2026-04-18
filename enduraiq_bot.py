#!/usr/bin/env python3
"""EnduraIQ Coach — Telegram Bot v2: Multi-user with CSV upload"""
 
import os
import csv
import io
import re
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
 
TOKEN = os.environ.get("BOT_TOKEN", "8744873375:AAFg9AGD4FK_ulE4zR3lb6O4cnK6P2Vl5-8")
 
# Store user data in memory
user_data = {}
 
# ── Zone Calculations ────────────────────────────────────
def get_zones(lthr):
    return {
        'Zone 1': (0, int(lthr * 0.81)),
        'Zone 2': (int(lthr * 0.81), int(lthr * 0.90)),
        'Zone 3': (int(lthr * 0.90), int(lthr * 0.94)),
        'Zone 4': (int(lthr * 0.94), int(lthr * 1.0)),
        'Zone 5': (int(lthr * 1.0), 999),
    }
 
def classify_zone(hr, zones):
    for name, (lo, hi) in zones.items():
        if lo <= hr < hi:
            return name
    return 'Zone 5'
 
def safe_int(val):
    try:
        return int(val.strip().strip('"').replace(',', ''))
    except:
        return 0
 
def safe_float(val):
    try:
        return float(val.strip().strip('"').replace(',', ''))
    except:
        return 0.0
 
# ── CSV Parsing ──────────────────────────────────────────
def detect_activity_type(text):
    first_line = text.split('\n')[0].lower()
    if 'swim stroke' in first_line or 'swolf' in first_line or 'lengths' in first_line:
        return 'swim'
    elif 'avg speed' in first_line and 'avg pace' not in first_line:
        return 'bike'
    else:
        return 'run'
 
def parse_run_csv(text):
    reader = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    header = next(reader)
    hr_col = pace_col = dist_col = time_col = None
    for i, h in enumerate(header):
        h_clean = h.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in h_clean: hr_col = i
        if 'avg pace' in h_clean and pace_col is None: pace_col = i
        if 'distance' in h_clean and dist_col is None: dist_col = i
        if 'cumulative time' in h_clean: time_col = i
    if hr_col is None: return None
    laps = []
    summary = None
    for row in reader:
        if not row: continue
        label = row[0].strip().strip('"')
        if label.lower() == 'summary':
            summary = {'avg_hr': safe_int(row[hr_col]), 'time': row[time_col].strip().strip('"') if time_col else '', 'distance': row[dist_col].strip().strip('"') if dist_col else ''}
            continue
        hr = safe_int(row[hr_col])
        if hr > 0:
            lap = {'lap': label, 'avg_hr': hr}
            if pace_col and pace_col < len(row): lap['pace'] = row[pace_col].strip().strip('"')
            laps.append(lap)
    return {'type': 'run', 'laps': laps, 'summary': summary}
 
def parse_bike_csv(text):
    reader = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    header = next(reader)
    hr_col = speed_col = dist_col = time_col = None
    for i, h in enumerate(header):
        h_clean = h.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in h_clean: hr_col = i
        if 'avg speed' in h_clean and speed_col is None: speed_col = i
        if 'distance' in h_clean and dist_col is None: dist_col = i
        if 'cumulative time' in h_clean: time_col = i
    if hr_col is None: return None
    laps = []
    summary = None
    for row in reader:
        if not row: continue
        label = row[0].strip().strip('"')
        if label.lower() == 'summary':
            summary = {'avg_hr': safe_int(row[hr_col]), 'time': row[time_col].strip().strip('"') if time_col else '', 'distance': row[dist_col].strip().strip('"') if dist_col else '', 'avg_speed': safe_float(row[speed_col]) if speed_col else 0}
            continue
        hr = safe_int(row[hr_col])
        if hr > 0:
            lap = {'lap': label, 'avg_hr': hr}
            if speed_col and speed_col < len(row): lap['speed'] = safe_float(row[speed_col])
            laps.append(lap)
    return {'type': 'bike', 'laps': laps, 'summary': summary}
 
def parse_swim_csv(text):
    reader = csv.reader(io.StringIO(text.replace('\r\n', '\n')))
    header = next(reader)
    hr_col = pace_col = swolf_col = dist_col = stroke_col = None
    for i, h in enumerate(header):
        h_clean = h.strip().strip('"').lower().replace('\n', ' ')
        if 'avg hr' in h_clean: hr_col = i
        if 'avg pace' in h_clean: pace_col = i
        if 'swolf' in h_clean: swolf_col = i
        if 'distance' in h_clean: dist_col = i
        if 'swim stroke' in h_clean: stroke_col = i
    if hr_col is None: return None
    sets = []
    summary = None
    for row in reader:
        if not row: continue
        label = row[1].strip().strip('"') if len(row) > 1 else ''
        if label.lower() == 'summary':
            summary = {'avg_hr': safe_int(row[hr_col]) if hr_col else 0}
            continue
        if stroke_col and stroke_col < len(row):
            stroke = row[stroke_col].strip().strip('"').lower()
            if stroke == 'rest' or stroke == '--': continue
        if '.' in label: continue
        hr = safe_int(row[hr_col]) if hr_col and hr_col < len(row) else 0
        if hr > 0 and label:
            s = {'set': label, 'avg_hr': hr}
            if pace_col and pace_col < len(row): s['pace'] = row[pace_col].strip().strip('"')
            if swolf_col and swolf_col < len(row): s['swolf'] = safe_int(row[swolf_col])
            if dist_col and dist_col < len(row): s['distance'] = row[dist_col].strip().strip('"')
            sets.append(s)
    return {'type': 'swim', 'sets': sets, 'summary': summary}
 
# ── Analysis Functions ───────────────────────────────────
def analyze_run(data, lthr):
    laps = data['laps']
    summary = data['summary']
    zones = get_zones(lthr)
    if len(laps) < 3: return "Not enough laps to analyze. Need at least 3 km."
    zone_counts = {'Zone 1': 0, 'Zone 2': 0, 'Zone 3': 0, 'Zone 4': 0, 'Zone 5': 0}
    for lap in laps:
        zone_counts[classify_zone(lap['avg_hr'], zones)] += 1
    total = len(laps)
    analysis_laps = laps[1:-2] if len(laps) > 5 else laps[1:]
    if len(analysis_laps) >= 4:
        mid = len(analysis_laps) // 2
        first_hr = sum(l['avg_hr'] for l in analysis_laps[:mid]) / mid
        second_hr = sum(l['avg_hr'] for l in analysis_laps[mid:]) / len(analysis_laps[mid:])
    else:
        first_hr, second_hr = laps[0]['avg_hr'], laps[-1]['avg_hr']
    drift = ((second_hr - first_hr) / first_hr) * 100
    avg_hr = summary['avg_hr'] if summary else sum(l['avg_hr'] for l in laps) // len(laps)
    pct_lthr = (avg_hr / lthr) * 100
    if pct_lthr < 81: run_type = "Easy / Recovery Run"
    elif pct_lthr < 90: run_type = "Aerobic / Zone 2 Run"
    elif pct_lthr < 94: run_type = "Tempo Run"
    elif pct_lthr < 100: run_type = "Threshold Run"
    else: run_type = "VO2max / Interval Session"
    dist = summary['distance'] if summary else str(len(laps))
    time = summary['time'] if summary else "N/A"
    msg = f"🏃 *RUN ANALYSIS*\n{dist} km · {time} · Avg HR {avg_hr}\n\n*Type:* {run_type}\nAvg HR = {pct_lthr:.0f}% of LTHR ({lthr})\n\n*Zone Distribution:*"
    for z, count in zone_counts.items():
        pct = count * 100 // total if total > 0 else 0
        bar = "█" * (pct // 5)
        msg += f"\n{z}: {count}/{total} ({pct}%) {bar}"
    msg += f"\n\n*Cardiac Drift:*\nFirst half: {first_hr:.0f} bpm\nSecond half: {second_hr:.0f} bpm\nDrift: {drift:.1f}%"
    if drift < 3: msg += "\n✅ Excellent aerobic base"
    elif drift < 5: msg += "\n✅ Good — solid aerobic system"
    elif drift < 8: msg += "\n⚠️ Moderate — more Zone 2 volume needed"
    else: msg += "\n🔴 High — aerobic base needs work"
    z2_ceil = zones['Zone 2'][1]
    if pct_lthr < 90:
        over = sum(1 for l in laps if l['avg_hr'] > z2_ceil)
        if over > 0: msg += f"\n\n*Coach:* ⚠️ {over} laps exceeded Zone 2 ceiling ({z2_ceil} bpm). Slow down on easy days."
        else: msg += f"\n\n*Coach:* Well-executed aerobic run. You stayed under Zone 2 ceiling ({z2_ceil}). This builds your engine."
    elif pct_lthr < 94: msg += "\n\n*Coach:* Solid tempo. Keep to once per week max."
    elif pct_lthr < 100: msg += "\n\n*Coach:* Hard session. Next 2 days should be easy/rest."
    else: msg += "\n\n*Coach:* High intensity. Make sure you recover properly."
    return msg
 
def analyze_bike_data(data, lthr):
    laps = data['laps']
    summary = data['summary']
    zones = get_zones(lthr)
    if len(laps) < 2: return "Not enough laps to analyze."
    zone_counts = {'Zone 1': 0, 'Zone 2': 0, 'Zone 3': 0, 'Zone 4': 0, 'Zone 5': 0}
    for lap in laps:
        zone_counts[classify_zone(lap['avg_hr'], zones)] += 1
    total = len(laps)
    mid = len(laps) // 2
    first_hr = sum(l['avg_hr'] for l in laps[:mid]) / mid
    second_hr = sum(l['avg_hr'] for l in laps[mid:]) / len(laps[mid:])
    drift = ((second_hr - first_hr) / first_hr) * 100
    avg_hr = summary['avg_hr'] if summary else sum(l['avg_hr'] for l in laps) // len(laps)
    avg_speed = summary.get('avg_speed', 0) if summary else 0
    dist = summary['distance'] if summary else 'N/A'
    time = summary['time'] if summary else 'N/A'
    msg = f"🚴 *BIKE ANALYSIS*\n{dist} km · {time} · Avg HR {avg_hr}"
    if avg_speed: msg += f" · {avg_speed:.1f} km/h"
    msg += "\n\n*Zone Distribution:*"
    for z, count in zone_counts.items():
        pct = count * 100 // total if total > 0 else 0
        bar = "█" * (pct // 5)
        msg += f"\n{z}: {count}/{total} ({pct}%) {bar}"
    msg += f"\n\n*Cardiac Drift:*\nFirst half: {first_hr:.0f} bpm\nSecond half: {second_hr:.0f} bpm\nDrift: {drift:+.1f}%"
    if drift < 0: msg += "\n✅ HR decreased — good settling"
    elif drift < 5: msg += "\n✅ Acceptable drift"
    else: msg += "\n⚠️ Significant drift — pacing too hard early"
    z3_floor = zones['Zone 3'][0]
    z2_ceil = zones['Zone 2'][1]
    high = sum(1 for l in laps if l['avg_hr'] >= z3_floor)
    if high > 0: msg += f"\n\n⚠️ *Intensity Flag:* {high} laps hit Zone 3+ (HR ≥{z3_floor}). Zone 2 ceiling = {z2_ceil}"
    if avg_speed > 0:
        t = 180 / avg_speed
        msg += f"\n\n*Ironman Projection:* At {avg_speed:.1f} km/h: ~{int(t)}h {int((t%1)*60)}min for 180km"
    msg += f"\n\n*Coach:* Ironman bike = Zone 2 only (HR {zones['Zone 2'][0]}-{z2_ceil}). Riding harder costs you the run."
    return msg
 
def analyze_swim_data(data):
    sets = [s for s in data['sets'] if s['avg_hr'] > 50]
    if len(sets) < 2: return "Not enough swim sets with HR data."
    msg = "🏊 *SWIM ANALYSIS*\n\n*Set Breakdown:*\n"
    for s in sets:
        line = f"Set {s['set']}: HR {s['avg_hr']}"
        if 'pace' in s and s['pace'] and s['pace'] != '--': line += f" · {s['pace']}/100m"
        if 'swolf' in s and s['swolf']: line += f" · SWOLF {s['swolf']}"
        msg += line + "\n"
    drift = ((sets[-1]['avg_hr'] - sets[0]['avg_hr']) / sets[0]['avg_hr']) * 100
    msg += f"\n*Cardiac Drift:* {sets[0]['avg_hr']} → {sets[-1]['avg_hr']} ({drift:.1f}%)"
    if drift > 15: msg += "\n🔴 High — aerobic swim base needs volume"
    elif drift > 8: msg += "\n⚠️ Moderate — build longer continuous swims"
    else: msg += "\n✅ Controlled drift"
    swolf_sets = [s for s in sets if 'swolf' in s and s['swolf'] > 0]
    if len(swolf_sets) >= 2:
        sc = swolf_sets[-1]['swolf'] - swolf_sets[0]['swolf']
        msg += f"\n\n*Efficiency:* SWOLF {swolf_sets[0]['swolf']} → {swolf_sets[-1]['swolf']} ({sc:+d})"
        if sc > 3: msg += "\n⚠️ Technique breaking down — add drill work"
    msg += "\n\n*Coach:* Build longer continuous swims (800-1500m) at easy pace. The goal is holding pace without HR climbing."
    return msg
 
# ── Bot Handlers ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """👋 *Welcome to EnduraIQ*
 
I'm your AI endurance coach. Send me your Garmin CSV files and I'll give you real coaching — not just charts.
 
*Get started in 2 steps:*
 
1️⃣ Set your zones — send me:
`run: 180 bike: 165`
(replace with your LTHR numbers)
Or use /defaults for estimated values
 
2️⃣ Export a workout from Garmin Connect as CSV and send it here
 
*Commands:*
/setup — How to set your LTHR
/defaults — Use estimated zones
/help — How to export from Garmin
/about — What I analyze
 
_Built by an athlete, for athletes._"""
    await update.message.reply_text(msg, parse_mode="Markdown")
 
async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """⚙️ *Setup Your Zones*
 
Send me your LTHR like this:
`run: 180 bike: 165`
 
*Don't know your LTHR?*
Do a 30-min all-out solo effort (run or bike). Your avg HR for the last 20 min is roughly your LTHR.
 
Or use /defaults to start with estimates."""
    await update.message.reply_text(msg, parse_mode="Markdown")
 
async def defaults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data[uid] = {'run_lthr': 175, 'bike_lthr': 170}
    msg = """✅ *Defaults Set*
Run LTHR: 175 · Bike LTHR: 170
 
Now send me a Garmin CSV file!"""
    await update.message.reply_text(msg, parse_mode="Markdown")
 
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """📖 *How to Export from Garmin*
 
1. Go to *connect.garmin.com* on a computer
2. Click *Activities*
3. Click any activity
4. Click the ⚙️ gear icon (top right)
5. Click *Export to CSV*
6. Send that file here
 
I'll analyze zone distribution, cardiac drift, pacing, and give you coaching notes."""
    await update.message.reply_text(msg, parse_mode="Markdown")
 
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """🧠 *What EnduraIQ Analyzes*
 
• *Cardiac Drift* — HR creep at same pace = aerobic fitness indicator
• *Zone Distribution* — Are you really doing 80/20?
• *Intensity Classification* — Easy vs tempo vs threshold vs VO2
• *Pacing Flags* — Started too hard? Faded? I catch it
• *Swim Efficiency* — SWOLF trends under fatigue
• *Ironman Projections* — Estimated race splits
 
Based on Friel's methodology and sports science research.
 
Free during beta. $15/mo after."""
    await update.message.reply_text(msg, parse_mode="Markdown")
 
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip().lower()
    if 'run:' in text or 'bike:' in text:
        run_lthr = 175
        bike_lthr = 170
        rm = re.search(r'run:\s*(\d+)', text)
        bm = re.search(r'bike:\s*(\d+)', text)
        if rm: run_lthr = int(rm.group(1))
        if bm: bike_lthr = int(bm.group(1))
        user_data[uid] = {'run_lthr': run_lthr, 'bike_lthr': bike_lthr}
        rz = get_zones(run_lthr)
        bz = get_zones(bike_lthr)
        msg = f"""✅ *Profile Set*
 
*Run (LTHR {run_lthr}):*
Z1: <{rz['Zone 1'][1]} · Z2: {rz['Zone 2'][0]}-{rz['Zone 2'][1]} · Z3: {rz['Zone 3'][0]}-{rz['Zone 3'][1]} · Z4: {rz['Zone 4'][0]}-{rz['Zone 4'][1]} · Z5: >{rz['Zone 5'][0]}
 
*Bike (LTHR {bike_lthr}):*
Z1: <{bz['Zone 1'][1]} · Z2: {bz['Zone 2'][0]}-{bz['Zone 2'][1]} · Z3: {bz['Zone 3'][0]}-{bz['Zone 3'][1]} · Z4: {bz['Zone 4'][0]}-{bz['Zone 4'][1]} · Z5: >{bz['Zone 5'][0]}
 
Now send me a Garmin CSV!"""
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    await update.message.reply_text("Send me a Garmin CSV file and I'll analyze it.\n\nUse /help for export instructions.\nUse /setup to set your zones.", parse_mode="Markdown")
 
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    profile = user_data.get(uid, {'run_lthr': 175, 'bike_lthr': 170})
    doc = update.message.document
    if not doc.file_name.endswith('.csv'):
        await update.message.reply_text("Please send a .csv file from Garmin Connect. Use /help for instructions.")
        return
    await update.message.reply_text("🔄 Analyzing your workout...")
    try:
        file = await doc.get_file()
        file_bytes = await file.download_as_bytearray()
        text = file_bytes.decode('utf-8', errors='ignore')
        activity_type = detect_activity_type(text)
        if activity_type == 'swim':
            data = parse_swim_csv(text)
            msg = analyze_swim_data(data) if data and len(data['sets']) >= 2 else "Couldn't parse swim data."
        elif activity_type == 'bike':
            data = parse_bike_csv(text)
            msg = analyze_bike_data(data, profile['bike_lthr']) if data and len(data['laps']) >= 2 else "Couldn't parse bike data."
        else:
            data = parse_run_csv(text)
            msg = analyze_run(data, profile['run_lthr']) if data and len(data['laps']) >= 2 else "Couldn't parse run data."
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}\n\nMake sure it's a CSV from Garmin Connect.")
 
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Welcome & setup"),
        BotCommand("setup", "Set your LTHR zones"),
        BotCommand("defaults", "Use default zones"),
        BotCommand("help", "How to export from Garmin"),
        BotCommand("about", "What EnduraIQ analyzes"),
    ])
 
def main():
    app = Application.builder().token(TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("defaults", defaults))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("EnduraIQ Coach bot v2 is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
 
if __name__ == "__main__":
    main()
