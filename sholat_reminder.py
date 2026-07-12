#!/usr/bin/env python3
"""Prayer time reminder — deployed to GitHub Actions.
Fetches daily prayer times from Aladhan API and sends Telegram notifications.
State persisted in state.json (auto-committed by the workflow).
Now with random hadith excerpts!
"""

import json
import os
import random
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

# === HADITH EXCERPTS (Shahih Bukhari & Muslim, terjemahan Indonesia) ===
HADITH_LIST = [
    # Keutamaan sholat tepat waktu
    {
        "arabic": "الصَّلَاةُ عَلَى وَقْتِهَا",
        "text": "Amalan yang paling dicintai Allah adalah sholat pada waktunya.",
        "source": "HR. Bukhari No. 527",
    },
    {
        "arabic": "أَرَأَيْتُمْ لَوْ أَنَّ نَهْرًا بِبَابِ أَحَدِكُمْ يَغْتَسِلُ مِنْهُ كُلَّ يَوْمٍ خَمْسَ مَرَّاتٍ",
        "text": "Bagaimana pendapatmu jika di depan pintu seseorang ada sungai, lalu ia mandi lima kali sehari? Seperti itulah perumpamaan sholat lima waktu — Allah menghapus dosa-dosa dengannya.",
        "source": "HR. Bukhari No. 528",
    },
    {
        "arabic": "إِنَّ أَوَّلَ مَا يُحَاسَبُ بِهِ الْعَبْدُ يَوْمَ الْقِيَامَةِ مِنْ عَمَلِهِ صَلَاتُهُ",
        "text": "Sesungguhnya amal yang pertama kali dihisab pada hari kiamat adalah sholatnya.",
        "source": "HR. Tirmidzi No. 413",
    },
    {
        "arabic": "بَيْنَ الرَّجُلِ وَبَيْنَ الشِّرْكِ وَالْكُفْرِ تَرْكُ الصَّلَاةِ",
        "text": "Batas antara seseorang dengan syirik dan kekafiran adalah meninggalkan sholat.",
        "source": "HR. Muslim No. 82",
    },
    {
        "arabic": "مَنْ حَافَظَ عَلَى الصَّلَوَاتِ الْخَمْسِ كَانَتْ لَهُ نُورًا وَبُرْهَانًا وَنَجَاةً يَوْمَ الْقِيَامَةِ",
        "text": "Barang siapa menjaga sholat lima waktu, maka ia akan menjadi cahaya, bukti, dan penyelamat baginya pada hari kiamat.",
        "source": "HR. Ahmad No. 6576",
    },
    {
        "arabic": "خَيْرُ الْأَعْمَالِ الصَّلَاةُ فِي أَوَّلِ وَقْتِهَا",
        "text": "Sebaik-baik amalan adalah sholat di awal waktunya.",
        "source": "HR. Tirmidzi No. 170",
    },
    # Subuh
    {
        "arabic": "مَنْ صَلَّى الصُّبْحَ فَهُوَ فِي ذِمَّةِ اللَّهِ",
        "text": "Barang siapa sholat Subuh, maka ia berada dalam jaminan Allah.",
        "source": "HR. Muslim No. 657",
    },
    {
        "arabic": "بَشِّرِ الْمَشَّائِينَ فِي الظُّلَمِ إِلَى الْمَسَاجِدِ بِالنُّورِ التَّامِّ يَوْمَ الْقِيَامَةِ",
        "text": "Berilah kabar gembira bagi orang-orang yang berjalan di kegelapan menuju masjid dengan cahaya yang sempurna pada hari kiamat.",
        "source": "HR. Abu Dawud No. 561",
    },
    # Dzuhur & Ashar
    {
        "arabic": "الَّذِينَ يُصَلُّونَ قَبْلَ طُلُوعِ الشَّمْسِ وَقَبْلَ غُرُوبِهَا لَنْ يَدْخُلُوا النَّارَ",
        "text": "Orang yang sholat sebelum terbit matahari (Subuh) dan sebelum terbenamnya (Ashar) tidak akan masuk neraka.",
        "source": "HR. Muslim No. 634",
    },
    {
        "arabic": "مَنْ تَرَكَ صَلَاةَ الْعَصْرِ فَقَدْ حَبِطَ عَمَلُهُ",
        "text": "Barang siapa meninggalkan sholat Ashar, maka terhapuslah amalannya.",
        "source": "HR. Bukhari No. 553",
    },
    # Maghrib & Isya
    {
        "arabic": "لَوْ يَعْلَمُونَ مَا فِي الْعَتَمَةِ وَالصُّبْحِ لَأَتَوْهُمَا وَلَوْ حَبْوًا",
        "text": "Seandainya mereka mengetahui keutamaan Isya dan Subuh, niscaya mereka akan mendatanginya meskipun dengan merangkak.",
        "source": "HR. Bukhari No. 657",
    },
    {
        "arabic": "مَنْ صَلَّى الْعِشَاءَ فِي جَمَاعَةٍ فَكَأَنَّمَا قَامَ نِصْفَ اللَّيْلِ",
        "text": "Barang siapa sholat Isya berjamaah, maka seakan-akan ia sholat separuh malam.",
        "source": "HR. Muslim No. 656",
    },
    # Umum
    {
        "arabic": "الصَّلَاةُ نُورٌ",
        "text": "Sholat itu adalah cahaya.",
        "source": "HR. Muslim No. 223",
    },
    {
        "arabic": "أَقِمِ الصَّلَاةَ لِذِكْرِي",
        "text": "Dirikanlah sholat untuk mengingat-Ku.",
        "source": "QS. Thaha: 14",
    },
    {
        "arabic": "إِنَّ الصَّلَاةَ تَنْهَىٰ عَنِ الْفَحْشَاءِ وَالْمُنكَرِ",
        "text": "Sesungguhnya sholat mencegah dari perbuatan keji dan mungkar.",
        "source": "QS. Al-Ankabut: 45",
    },
    {
        "arabic": "حَافِظُوا عَلَى الصَّلَوَاتِ وَالصَّلَاةِ الْوُسْطَىٰ",
        "text": "Peliharalah semua sholat dan sholat wustha (Ashar).",
        "source": "QS. Al-Baqarah: 238",
    },
    {
        "arabic": "رَكَعَتَانِ فِي جَوْفِ اللَّيْلِ خَيْرٌ مِنَ الدُّنْيَا وَمَا فِيهَا",
        "text": "Dua rakaat di keheningan malam lebih baik dari dunia dan seisinya.",
        "source": "HR. Muslim No. 725",
    },
    {
        "arabic": "مَنْ سَرَّهُ أَنْ يَلْقَى اللَّهَ غَدًا مُسْلِمًا فَلْيُحَافِظْ عَلَى هَؤُلَاءِ الصَّلَوَاتِ",
        "text": "Barang siapa ingin bertemu Allah esok dalam keadaan muslim, hendaklah ia menjaga sholat lima waktu ini.",
        "source": "HR. Muslim No. 632",
    },
    {
        "arabic": "لَا صَلَاةَ لِمَنْ لَمْ يَقْرَأْ بِفَاتِحَةِ الْكِتَابِ",
        "text": "Tidak sah sholat seseorang yang tidak membaca Al-Fatihah.",
        "source": "HR. Bukhari No. 756",
    },
    {
        "arabic": "أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ",
        "text": "Kondisi paling dekat seorang hamba dengan Tuhannya adalah ketika ia sedang sujud.",
        "source": "HR. Muslim No. 482",
    },
    {
        "arabic": "مَنْ بَنَىٰ مَسْجِدًا لِلَّهِ بَنَى اللَّهُ لَهُ بَيْتًا فِي الْجَنَّةِ",
        "text": "Barang siapa membangun masjid karena Allah, niscaya Allah bangunkan rumah baginya di surga.",
        "source": "HR. Bukhari No. 450",
    },
    {
        "arabic": "إِذَا سَمِعْتُمُ الْمُؤَذِّنَ فَقُولُوا مِثْلَ مَا يَقُولُ",
        "text": "Apabila kalian mendengar muadzin, ucapkanlah seperti yang ia ucapkan.",
        "source": "HR. Muslim No. 384",
    },
    {
        "arabic": "خَيْرُ صُفُوفِ الرِّجَالِ أَوَّلُهَا وَشَرُّهَا آخِرُهَا",
        "text": "Sebaik-baik shaf laki-laki adalah yang paling depan, dan seburuk-buruknya adalah yang paling belakang.",
        "source": "HR. Muslim No. 440",
    },
    {
        "arabic": "لَا يَزَالُ الْعَبْدُ فِي صَلَاةٍ مَا كَانَتِ الصَّلَاةُ تَحْبِسُهُ",
        "text": "Seorang hamba senantiasa dianggap dalam keadaan sholat selama ia menunggu sholat.",
        "source": "HR. Bukhari No. 659",
    },
    {
        "arabic": "مَنْ تَوَضَّأَ فَأَحْسَنَ الْوُضُوءَ ثُمَّ خَرَجَ إِلَى الْمَسْجِدِ كُتِبَ لَهُ بِكُلِّ خُطْوَةٍ حَسَنَةٌ",
        "text": "Barang siapa berwudhu dengan sempurna lalu keluar menuju masjid, maka setiap langkahnya dicatat sebagai kebaikan.",
        "source": "HR. Muslim No. 653",
    },
    {
        "arabic": "الْعَهْدُ الَّذِي بَيْنَنَا وَبَيْنَهُمُ الصَّلَاةُ فَمَنْ تَرَكَهَا فَقَدْ كَفَرَ",
        "text": "Perjanjian antara kita dan mereka (orang munafik) adalah sholat. Barang siapa meninggalkannya, maka ia telah kafir.",
        "source": "HR. Tirmidzi No. 2621",
    },
]


def get_random_hadith():
    """Return a random hadith excerpt."""
    return random.choice(HADITH_LIST)


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

        hadith = get_random_hadith()
        now_str = now.strftime("%H:%M")
        prayer_list = "\n".join(f"\u25b6 {r}" for r in reminders)

        lines = [
            f"\U0001f54c **Waktu Sholat — {today_str}** \U0001f54c",
            "",
            prayer_list,
            "",
            "—",
            f"_{hadith['arabic']}_",
            f"_{hadith['text']}_",
            f"\U0001f4d6 *{hadith['source']}*",
            "",
            f"_Notifikasi dikirim pukul {now_str} WIB via GitHub Actions_",
        ]

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
