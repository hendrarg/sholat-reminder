#!/usr/bin/env python3
"""Prayer time reminder — deployed to GitHub Actions.
Fetches daily prayer times from MyQuran first, with Aladhan fallback, and sends Telegram notifications.
State persisted in state.json (auto-committed by the workflow).
Now with random hadith excerpts!
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen, Request

# === CONFIG ===
CITY = os.environ.get("PRAYER_CITY", "Jakarta")
COUNTRY = os.environ.get("PRAYER_COUNTRY", "Indonesia")
METHOD = int(os.environ.get("PRAYER_METHOD", "20"))  # 20 = Kemenag RI
WINDOW_MINUTES = int(os.environ.get("PRAYER_WINDOW", "10"))
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
PRAYER_PROVIDER = os.environ.get("PRAYER_PROVIDER", "auto").strip().lower()
MYQURAN_CITY_ID = os.environ.get("PRAYER_CITY_ID", "").strip()
API_RETRIES = int(os.environ.get("PRAYER_API_RETRIES", "3"))
API_BACKOFF_SECONDS = float(os.environ.get("PRAYER_API_BACKOFF", "1.5"))

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


def request_json(url, *, timeout=10):
    """Fetch JSON with retries for transient HTTP/network errors."""
    last_error = None
    retry_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, API_RETRIES + 1):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "Hermes-SholatReminder/3.0",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as exc:
            last_error = exc
            if exc.code not in retry_statuses or attempt == API_RETRIES:
                break
        except URLError as exc:
            last_error = exc
            if attempt == API_RETRIES:
                break

        sleep_for = API_BACKOFF_SECONDS * attempt
        print(
            f"Transient API error on {url} (attempt {attempt}/{API_RETRIES}); retrying in {sleep_for:.1f}s",
            file=sys.stderr,
        )
        time.sleep(sleep_for)

    raise last_error


def normalize_prayer_value(value):
    """Strip extra annotations from API time values."""
    return str(value).split()[0]


def resolve_myquran_city_id():
    """Resolve the MyQuran city id from config or search endpoint."""
    if MYQURAN_CITY_ID:
        return MYQURAN_CITY_ID

    search_url = f"https://api.myquran.com/v2/sholat/kota/cari/{quote(CITY)}"
    data = request_json(search_url)
    if not data.get("status") or not data.get("data"):
        raise RuntimeError(f"MyQuran city search failed for {CITY!r}: {data}")

    normalized_city = CITY.strip().lower()
    matches = data["data"]

    def match_rank(item):
        lokasi = str(item.get("lokasi", "")).strip().lower()
        if lokasi == normalized_city:
            return 0
        if normalized_city in lokasi:
            return 1
        return 2

    best = sorted(matches, key=match_rank)[0]
    city_id = str(best.get("id", "")).strip()
    if not city_id:
        raise RuntimeError(f"MyQuran search returned invalid city data for {CITY!r}: {best}")
    return city_id


def fetch_prayer_times_myquran(now):
    """Fetch today's prayer times from MyQuran."""
    city_id = resolve_myquran_city_id()
    url = (
        f"https://api.myquran.com/v2/sholat/jadwal/{city_id}"
        f"/{now:%Y}/{now:%m}/{now:%d}"
    )
    data = request_json(url)
    if not data.get("status"):
        raise RuntimeError(f"MyQuran API error: {data}")

    jadwal = data["data"]["jadwal"]
    return {
        "Fajr": normalize_prayer_value(jadwal["subuh"]),
        "Dhuhr": normalize_prayer_value(jadwal["dzuhur"]),
        "Asr": normalize_prayer_value(jadwal["ashar"]),
        "Maghrib": normalize_prayer_value(jadwal["maghrib"]),
        "Isha": normalize_prayer_value(jadwal["isya"]),
    }


def fetch_prayer_times_aladhan():
    """Fetch today's prayer times from Aladhan API."""
    url = (
        f"https://api.aladhan.com/v1/timingsByCity"
        f"?city={quote(CITY)}&country={quote(COUNTRY)}&method={METHOD}"
    )
    data = request_json(url)
    if data.get("code") != 200:
        raise RuntimeError(f"Aladhan API error: {data}")
    timings = data["data"]["timings"]
    return {k: normalize_prayer_value(timings[k]) for k in PRAYER_NAMES}


def fetch_prayer_times(now):
    """Fetch today's prayer times with MyQuran first, Aladhan fallback."""
    providers = ["myquran", "aladhan"]
    if PRAYER_PROVIDER in {"myquran", "aladhan"}:
        providers = [PRAYER_PROVIDER]

    errors = []
    for provider in providers:
        try:
            if provider == "myquran":
                prayers = fetch_prayer_times_myquran(now)
            else:
                prayers = fetch_prayer_times_aladhan()
            print(f"Prayer times source: {provider}")
            return prayers
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            print(f"Prayer source failed: {provider}: {exc}", file=sys.stderr)

    raise RuntimeError("; ".join(errors))


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
        prayers = fetch_prayer_times(now)
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
