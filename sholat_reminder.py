#!/usr/bin/env python3
"""Prayer time reminder — deployed to GitHub Actions.
Fetches daily prayer times from Aladhan API and sends Telegram notifications.
State persisted in state.json (auto-committed by the workflow).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request

# === CONFIG ===
CITY = os.environ.get("PRAYER_CITY", "Jakarta")
COUNTRY = os.environ.get("PRAYER_COUNTRY", "Indonesia")
METHOD = int(os.environ.get("PRAYER_METHOD", "20"))  # 20 = Kemenag RI
WINDOW_MINUTES = int(os.environ.get("PRAYER_WINDOW", "3"))
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# WIB timezone (UTC+7)
WIB = timezone(timedelta(hours=7))

PRAYER_NAMES = {
    "Fajr": "\U0001f305 Subuh",
    "Dhuhr": "\u2600\ufe0f Dzuhur",
    "Asr": "\U0001f324\ufe0f Ashar",
    "Maghrib": "\U0001f307 Maghrib",
    "Isha": "\U0001f319 Isya",
}


def fetch_prayer_times():
    """Fetch today's prayer times from Aladhan API."""
    url = (
        f"https://api.aladhan.com/v1/timingsByCity"
        f"?city={CITY}&country={COUNTRY}&method={METHOD}"
    )
    req = Request(url, headers={"User-Agent": "Hermes-SholatReminder/2.0"})
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data["code"] != 200:
        raise RuntimeError(f"API error: {data}")
    timings = data["data"]["timings"]
    return {k: timings[k] for k in PRAYER_NAMES}


def load_state():
    """Load state from JSON file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    """Save state to JSON file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def parse_time(time_str):
    """Parse 'HH:MM' (24h) to (hour, minute)."""
    h, m = map(int, time_str.split(":"))
    return h, m


def send_telegram(text):
    """Send message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def main():
    # GitHub Actions runs in UTC — convert to WIB
    now = datetime.now(timezone.utc).astimezone(WIB)
    today_str = now.strftime("%Y-%m-%d")

    # Fetch prayer times
    try:
        prayers = fetch_prayer_times()
    except Exception as e:
        print(f"Failed to fetch prayer times: {e}", file=sys.stderr)
        sys.exit(1)

    # Load state, reset if new day
    state = load_state()
    if state.get("date") != today_str:
        state = {"date": today_str}

    reminders = []

    for key, name in PRAYER_NAMES.items():
        if key not in prayers:
            continue

        prayer_h, prayer_m = parse_time(prayers[key])
        diff = (now.hour * 60 + now.minute) - (prayer_h * 60 + prayer_m)

        if abs(diff) <= WINDOW_MINUTES and key not in state:
            state[key] = now.strftime("%H:%M")
            reminders.append(f"{name}: {prayers[key]} WIB")

    # If anything changed, save state
    if reminders:
        save_state(state)

        now_str = now.strftime("%H:%M")
        lines = [f"\U0001f54c **Waktu Sholat — {today_str}** \U0001f54c", ""]
        for r in reminders:
            lines.append(f"\u25b6 {r}")
        lines.append("")
        lines.append(f"_Notifikasi dikirim pukul {now_str} WIB via GitHub Actions_")

        message = "\n".join(lines)
        print(f"Sending notification:\n{message}")
        send_telegram(message)
    else:
        # Check if we need to save state (new day)
        if not os.path.exists(STATE_FILE) or state.get("date") != load_state().get("date"):
            save_state(state)
            print(f"New day: state initialized for {today_str}")
        else:
            print(f"No prayers in window. Current: {now.strftime('%H:%M')} WIB")


if __name__ == "__main__":
    main()
