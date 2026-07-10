# Sholat Reminder

Pengingat waktu sholat 5 waktu via GitHub Actions + Telegram.

## Cara Kerja
- Cron tiap 5 menit (04:00-19:00 WIB)
- Fetch jadwal dari [Aladhan API](https://aladhan.com/)
- Kirim notif ke Telegram dalam window ±3 menit

## Setup
1. Bikin GitHub repo
2. Tambah secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. Push — workflow auto jalan
