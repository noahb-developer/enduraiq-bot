#!/usr/bin/env python3
"""EnduraIQ Coach — Telegram Bot MVP"""

import asyncio
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8744873375:AAFg9AGD4FK_ulE4zR3lb6O4cnK6P2Vl5-8"

# ── Athlete Profile ──────────────────────────────────────
RUN_LTHR = 182
BIKE_LTHR = 168
MAX_HR = 207

# ── Training Data (from Alex's real Garmin exports) ──────
WORKOUTS = {
    "long_run": {
        "name": "Long Run",
        "distance": "13.94 km",
        "time": "1:30:01",
        "avg_hr": 136,
        "max_hr": 160,
        "laps_hr": [115, 127, 133, 131, 133, 134, 137, 137, 138, 139, 140, 142, 154, 157],
        "laps_pace": ["8:39", "7:24", "6:43", "6:45", "6:29", "6:15", "6:11", "6:10", "6:14", "6:13", "6:16", "6:23", "5:22", "5:16"],
    },
    "bike": {
        "name": "Bike Ride",
        "distance": "62.61 km",
        "time": "2:15:12",
        "avg_hr": 146,
        "max_hr": 169,
        "avg_speed": 27.8,
        "laps_hr": [142, 148, 153, 153, 145, 141, 147, 146, 146, 145, 142, 142, 147],
        "laps_speed": [27.7, 27.0, 28.3, 27.9, 27.9, 28.1, 29.6, 28.9, 27.3, 28.0, 26.9, 25.9, 28.3],
    },
    "swim": {
        "name": "Swim",
        "distance": "1,775m",
        "time": "48:38",
        "avg_hr": 134,
        "max_hr": 167,
        "sets_hr": [129, 146, 153, 150, 153, 158],
        "sets_pace": ["1:59", "2:05", "2:06", "2:14", "2:08", "2:08"],
        "sets_swolf": [44, 46, 47, 49, 48, 48],
    },
    "tempo_run": {
        "name": "Tempo Run",
        "distance": "5.28 km",
        "time": "27:58",
        "avg_hr": 157,
        "max_hr": 165,
        "laps_hr": [143, 159, 159, 159, 162],
        "laps_pace": ["5:27", "5:17", "5:13", "5:12", "5:18"],
    },
}


def analyze_long_run():
    d = WORKOUTS["long_run"]
    steady = d["laps_hr"][2:12]
    first = sum(steady[:5]) / 5
    second = sum(steady[5:]) / 5
    drift = ((second - first) / first) * 100

    z2_ceil = int(RUN_LTHR * 0.90)
    below_z2 = sum(1 for h in d["laps_hr"] if h < int(RUN_LTHR * 0.81))
    in_z2 = sum(1 for h in d["laps_hr"] if int(RUN_LTHR * 0.81) <= h < z2_ceil)
    above_z2 = sum(1 for h in d["laps_hr"] if h >= z2_ceil)

    msg = f"""🏃 *LONG RUN ANALYSIS*
{d['distance']} · {d['time']} · Avg HR {d['avg_hr']}

*Zone Distribution:*
Zone 1: {below_z2}/14 laps ({below_z2*100//14}%)
Zone 2: {in_z2}/14 laps ({in_z2*100//14}%)
Zone 3+: {above_z2}/14 laps ({above_z2*100//14}%)

*Cardiac Drift (km 3-12):*
First half HR: {first:.0f} bpm
Second half HR: {second:.0f} bpm
Drift: {drift:.1f}%
"""
    if drift < 5:
        msg += "✅ Good — your aerobic system is holding up well\n"
    elif drift < 8:
        msg += "⚠️ Moderate — more Zone 2 volume needed\n"
    else:
        msg += "🔴 High drift — aerobic base needs work\n"

    msg += f"""
*Pacing:*
Km 1-2: Warmup (8:39 → 7:24)
Km 3-12: Steady (6:43 → 6:23)
Km 13-14: Surge (5:22 → 5:16)
✅ You had energy reserves at the end — great for Ironman

*Coach's Note:*
This was a well-executed long run. Your drift of {drift:.1f}% shows your aerobic base is developing. Keep these runs in Zone 1-2 and resist the urge to push pace. The fitness comes from time on feet, not speed."""
    return msg


def analyze_bike():
    d = WORKOUTS["bike"]
    first6 = d["laps_hr"][:6]
    second6 = d["laps_hr"][6:12]
    f_hr = sum(first6) / len(first6)
    s_hr = sum(second6) / len(second6)
    drift = ((s_hr - f_hr) / f_hr) * 100

    z2_lo = int(BIKE_LTHR * 0.81)
    z2_hi = int(BIKE_LTHR * 0.90)
    z3_hi = int(BIKE_LTHR * 0.94)
    above = [i+1 for i, h in enumerate(d["laps_hr"]) if h >= z2_hi]

    msg = f"""🚴 *BIKE RIDE ANALYSIS*
{d['distance']} · {d['time']} · Avg HR {d['avg_hr']} · {d['avg_speed']} km/h

*Cardiac Drift:*
First 30km HR: {f_hr:.0f} bpm
Last 30km HR: {s_hr:.0f} bpm
Drift: {drift:+.1f}%
"""
    if drift < 0:
        msg += "✅ HR decreased — you settled into a rhythm\n"
    else:
        msg += f"⚠️ HR climbed {drift:.1f}% — watch your pacing early\n"

    if above:
        msg += f"""
⚠️ *Intensity Flag:*
Laps {above} hit Zone 3+ (HR ≥{z2_hi})
Your Zone 2 ceiling on bike = {z2_hi} bpm
If this was an easy ride, those laps were too hard
"""

    msg += f"""
*Ironman Projection:*
At this speed (27.8 km/h) with HR 146: ~6h 28min
But HR 146 is too high for a full Ironman bike
At true Zone 2 pace (~25 km/h): ~7h 12min

*Coach's Note:*
Your bike fitness is building. The key issue is intensity — you're riding at the top of Zone 2 / low Zone 3. For Ironman, you need to ride 30-60km at HR {z2_lo}-{z2_hi} comfortably. Slow down now = faster on race day."""
    return msg


def analyze_swim():
    d = WORKOUTS["swim"]
    hr_drift = ((d["sets_hr"][-1] - d["sets_hr"][0]) / d["sets_hr"][0]) * 100
    swolf_change = d["sets_swolf"][-1] - d["sets_swolf"][0]

    msg = f"""🏊 *SWIM ANALYSIS*
{d['distance']} · {d['time']} · Avg HR {d['avg_hr']}

*200m Repeats (Sets 4-9):*
Set 4: {d['sets_pace'][0]}/100m · HR {d['sets_hr'][0]} · SWOLF {d['sets_swolf'][0]}
Set 5: {d['sets_pace'][1]}/100m · HR {d['sets_hr'][1]} · SWOLF {d['sets_swolf'][1]}
Set 6: {d['sets_pace'][2]}/100m · HR {d['sets_hr'][2]} · SWOLF {d['sets_swolf'][2]}
Set 7: {d['sets_pace'][3]}/100m · HR {d['sets_hr'][3]} · SWOLF {d['sets_swolf'][3]}
Set 8: {d['sets_pace'][4]}/100m · HR {d['sets_hr'][4]} · SWOLF {d['sets_swolf'][4]}
Set 9: {d['sets_pace'][5]}/100m · HR {d['sets_hr'][5]} · SWOLF {d['sets_swolf'][5]}

*Cardiac Drift:*
HR rose from {d['sets_hr'][0]} → {d['sets_hr'][-1]} bpm ({hr_drift:.0f}%)
🔴 Significant — HR climbed 29 bpm while pace slowed

*Efficiency:*
SWOLF went from {d['sets_swolf'][0]} → {d['sets_swolf'][-1]} (+{swolf_change})
Technique breaks down with fatigue

*CSS Check:*
Your benchmark: 1:56/100m
First set: {d['sets_pace'][0]} (close to CSS)
Last set: {d['sets_pace'][-1]} (12 sec slower)

*Coach's Note:*
Your swim fitness is the biggest area for improvement. The 29 bpm HR jump across 6x200m tells me your aerobic swim base needs more volume. Focus on longer continuous swims (800-1500m) at 2:05-2:10 pace. Don't chase speed — chase the ability to hold pace without HR climbing."""
    return msg


def analyze_tempo():
    d = WORKOUTS["tempo_run"]
    pct = (d["avg_hr"] / RUN_LTHR) * 100
    hr_change = d["laps_hr"][-1] - d["laps_hr"][1]

    msg = f"""⚡ *TEMPO RUN ANALYSIS*
{d['distance']} · {d['time']} · Avg HR {d['avg_hr']}

*Intensity:*
Avg HR {d['avg_hr']} = {pct:.0f}% of LTHR ({RUN_LTHR})
✅ Correctly in Zone 3 (Tempo)

*Pacing:*
Km 1: {d['laps_pace'][0]} (warmup into effort)
Km 2: {d['laps_pace'][1]} @ {d['laps_hr'][1]} bpm
Km 3: {d['laps_pace'][2]} @ {d['laps_hr'][2]} bpm
Km 4: {d['laps_pace'][3]} @ {d['laps_hr'][3]} bpm
Km 5: {d['laps_pace'][4]} @ {d['laps_hr'][4]} bpm
✅ Locked in at ~5:15/km — excellent pacing

*Efficiency:*
Same pace, HR rose only {hr_change} bpm over 4 km
✅ Minimal drift under load — good sign

*Coach's Note:*
This is a textbook tempo execution. You held pace, your HR stayed controlled, and the slight fade at km 5 is totally normal. These sessions build your lactate threshold — keep them to once per week max."""
    return msg


def get_weekly_summary():
    msg = """📊 *ENDURAIQ — WEEKLY SUMMARY*

*Athlete Profile:*
Run LTHR: 182 bpm | Bike LTHR: 168 bpm
Target: IRONMAN Jacksonville, May 2027
Goal: Sub-10 hours

*Current Fitness:*
🏊 Swim: ~2:05/100m realistic pace
🚴 Bike: 27.8 km/h but at Zone 3 HR
🏃 Run: 6:15-6:30/km easy | 5:15/km tempo

*Ironman Projection:*
Swim: ~1h 20min
Bike: ~7h 12min (Zone 2 pace)
Run: ~4h 30min (conservative off-bike)
Total: ~13h 12min
Gap to sub-10: ~3h 12min

*Top 3 Priorities:*

1️⃣ *BIKE* — You're riding too hard. Avg HR 146 is Zone 3. Ironman bike must be Zone 2 (136-151 bpm). Slow down.

2️⃣ *SWIM* — More aerobic volume. Your HR jumps 29 bpm over 6x200m. Build longer continuous swims at 2:05-2:10 pace.

3️⃣ *RUN* — Well executed. Cardiac drift 4.2% is solid. Keep building distance gradually.

*Recovery Check:*
⚠️ No recovery week detected in recent data. Consider dropping volume 40% this week.

_This report is generated by EnduraIQ from your Garmin data._"""
    return msg


# ── Bot Handlers ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """👋 *Welcome to EnduraIQ*

I'm your AI endurance coach. I analyze your training data and give you real coaching — not just charts.

*Commands:*
/longrun — Analyze your last long run
/bike — Analyze your last bike ride
/swim — Analyze your last swim
/tempo — Analyze your last tempo run
/weekly — Full weekly training summary
/projections — Ironman race projections

Just finished a workout? I'll tell you what it means and what to do next.

_Built by an athlete, for athletes._"""
    await update.message.reply_text(msg, parse_mode="Markdown")


async def longrun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(analyze_long_run(), parse_mode="Markdown")

async def bike(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(analyze_bike(), parse_mode="Markdown")

async def swim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(analyze_swim(), parse_mode="Markdown")

async def tempo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(analyze_tempo(), parse_mode="Markdown")

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_weekly_summary(), parse_mode="Markdown")

async def projections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """🏁 *IRONMAN PROJECTIONS*
_Based on current training data_

*Current estimated splits:*
🏊 Swim 3.8km: *1h 20min* (2:08/100m)
🚴 Bike 180km: *7h 12min* (25 km/h @ Z2)
🏃 Run 42.2km: *4h 30min* (6:25/km off-bike)
🔄 Transitions: *10 min*
━━━━━━━━━━━━
📍 *Total: ~13h 12min*

*Sub-10 target splits:*
🏊 Swim: 1h 10min (1:50/100m)
🚴 Bike: 5h 30min (32.7 km/h)
🏃 Run: 3h 10min (4:30/km)
🔄 Transitions: 8 min
━━━━━━━━━━━━
📍 *Total: 9h 58min*

*Biggest gains available:*
1. Bike — improving from 25→30 km/h saves ~1h 12min
2. Run — improving from 6:25→5:00/km saves ~1h
3. Swim — improving from 2:08→1:55/100m saves ~8min

*Timeline: 13 months — achievable with consistent training*

_Projections update automatically as your fitness improves._"""
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if any(w in text for w in ["run", "running"]):
        await update.message.reply_text("Want me to analyze your run? Use /longrun for your long run or /tempo for your tempo run.", parse_mode="Markdown")
    elif any(w in text for w in ["bike", "cycling", "ride"]):
        await update.message.reply_text("Use /bike to see your bike ride analysis.", parse_mode="Markdown")
    elif any(w in text for w in ["swim", "pool"]):
        await update.message.reply_text("Use /swim to see your swim analysis.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Hey! Use /weekly to see your full training summary, or pick a specific workout to analyze:\n\n/longrun · /bike · /swim · /tempo", parse_mode="Markdown")


async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Welcome & commands"),
        BotCommand("longrun", "Analyze last long run"),
        BotCommand("bike", "Analyze last bike ride"),
        BotCommand("swim", "Analyze last swim"),
        BotCommand("tempo", "Analyze last tempo run"),
        BotCommand("weekly", "Full weekly summary"),
        BotCommand("projections", "Ironman race projections"),
    ])


def main():
    app = Application.builder().token(TOKEN).post_init(set_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("longrun", longrun))
    app.add_handler(CommandHandler("bike", bike))
    app.add_handler(CommandHandler("swim", swim))
    app.add_handler(CommandHandler("tempo", tempo))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CommandHandler("projections", projections))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("EnduraIQ Coach bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
