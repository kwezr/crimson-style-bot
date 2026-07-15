# Telegram E-commerce Bot + WebApp

## Fayllar tuzilishi
```
shop/
├── bot.py              # Bot logikasi + admin panel + HTTP API server
├── database.py         # SQLite bilan ishlash funksiyalari
├── requirements.txt
└── webapp/
    ├── index.html       # Do'kon sahifasi (dizayn)
    └── script.js        # Savat, promokod, botga fetch() orqali yuborish
```

## O'rnatish

```bash
pip install -r requirements.txt
```

## Sozlash (`.env` fayl orqali)

Maxfiy ma'lumotlar (token va h.k.) endi kod ichida emas, `.env` faylida
saqlanadi. Shu sababli:

1. `.env.example` faylini nusxalab, nomini `.env` ga o'zgartiring:
   ```bash
   cp .env.example .env
   ```
2. `.env` faylni oching va quyidagilarni to'ldiring:
   - `BOT_TOKEN` — @BotFather dan olingan token.
   - `SUPER_ADMIN_IDS` — bosh admin(lar)ning Telegram user_id(lari), vergul bilan.
   - `PUBLIC_BASE_URL` — botingiz ishlaydigan **https** manzil.
     Telegram WebApp faqat https manzillarni qabul qiladi, shu sababli
     lokal test uchun tunnel kerak bo'ladi, masalan:

     ```bash
     ngrok http 8080
     ```

     Natijada olingan `https://xxxx.ngrok-free.app` manzilini
     `PUBLIC_BASE_URL` ga yozing.

⚠️ **`.env` faylni hech qachon boshqalarga yubormang yoki GitHub/arxivga
qo'shmang** — u sizning maxfiy tokeningizni saqlaydi (`.gitignore` faylida
bu allaqachon istisno qilingan).

## Ishga tushirish

```bash
python bot.py
```

Bu bir vaqtning o'zida:
- Telegram botni (polling rejimida) ishga tushiradi,
- `webapp/` papkasini `http://localhost:8080/app` orqali serve qiladi,
- `/api/products`, `/api/promocode/{code}`, `/api/checkout` API larini ochadi.

## Mijoz uchun to'liq jarayon (boshidan oxirigacha)

1. Mijoz botga `/start` yuboradi → "🛍 Do'konni ochish" tugmasi chiqadi.
2. Tugmani bosib WebApp (do'kon sahifasi) ochiladi — mahsulotlar kartalarda ko'rinadi.
3. Mahsulotni bosib tafsilotini ko'radi, razmer bo'lsa tanlaydi, savatga qo'shadi.
4. Pastda savat paneli chiqadi — xohlasa promokod kiritadi ("Qo'llash"), umumiy summa yangilanadi.
5. "Sotib olish" tugmasini bosadi:
   - Server narxni bazadan qayta hisoblab, buyurtmani yaratadi (brauzerdan kelgan narxga ishonilmaydi).
   - Mijozga botda: "✅ Buyurtmangiz qabul qilindi" + **to'lov uchun karta raqami(lari)** yuboriladi.
   - Shu zahoti mijozdan **manzil so'raladi** (tugma orqali joylashuv yuborish yoki "🏬 O'zim olib ketaman").
6. Agar manzil yuborsa:
   - Do'kon sozlangan bo'lsa — masofa (km) va **yetkazib berish narxi avtomatik hisoblanadi**, mijozga umumiy summa (mahsulot + yetkazish) ko'rsatiladi.
   - Manzil xarita ko'rinishida + Google Maps havolasi bilan **adminga ham boradi**.
7. Admin buyurtma xabarida "✅ Tasdiqlash" yoki "❌ Bekor qilish" tugmasini bosadi → mijozga natija haqida avtomatik xabar boradi.

## Admin qila oladigan ishlar (`/admin`)

- 🌐 **Veb admin panel** — `/admin` buyrug'idagi "Veb admin panelni ochish"
  tugmasi orqali to'liq grafik panelda mahsulot, promokod, karta,
  buyurtma va adminlarni boshqarish (Telegram bot buyruqlarisiz).
- ➕/🗑 Mahsulot qo'shish, o'chirish, narxini o'zgartirish
- 🏷 Promokod qo'shish/o'chirish
- 💳 To'lov kartasi qo'shish/o'chirish (`/cards`)
- 📍 Yetkazib berish sozlamalari — do'kon joylashuvi, 1 km narxi, bazaviy narx (`/delivery`)
- 📋 Mahsulotlar, 📦 buyurtmalar, 👤 adminlar ro'yxati
- 👑 Bosh adminlar: yangi admin qo'shish/o'chirish
- 🧾 Mijoz to'lov chekini (screenshot) botga rasm qilib yuborsa, u
  avtomatik ravishda barcha adminlarga tasdiqlash/bekor qilish
  tugmalari bilan yuboriladi.

## Diqqat
- `photo_url` maydoniga rasm havolasini kiritsangiz, mahsulot kartasida
  rasm ko'rinadi (hozircha admin panelda rasm yuklash botga emas,
  faqat URL orqali ishlaydi).
- Yetkazib berish narxi to'g'ri chiziq (havo yo'li) masofasi bo'yicha
  hisoblanadi — real yo'l uzunligidan biroz farq qilishi mumkin.
- Ishlab chiqarish (production) uchun `PUBLIC_BASE_URL`ni doimiy domenga
  o'tkazing va serverni `systemd`/`docker` orqali doimiy ishlaydigan
  qilib sozlang.
