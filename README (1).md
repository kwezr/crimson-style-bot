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

## Sozlash (`bot.py` ichida)

1. `BOT_TOKEN` — @BotFather dan olingan token.
2. `SUPER_ADMIN_IDS` — bosh admin(lar)ning Telegram user_id ro'yxati.
3. `PUBLIC_BASE_URL` — botingiz ishlaydigan **https** manzil.
   Telegram WebApp faqat https manzillarni qabul qiladi, shu sababli
   lokal test uchun tunnel kerak bo'ladi, masalan:

   ```bash
   ngrok http 8080
   ```

   Natijada olingan `https://xxxx.ngrok-free.app` manzilini
   `PUBLIC_BASE_URL` ga yozing.

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

- ➕/🗑 Mahsulot qo'shish, o'chirish, narxini o'zgartirish
- 🏷 Promokod qo'shish/o'chirish
- 💳 To'lov kartasi qo'shish/o'chirish (`/cards`)
- 📍 Yetkazib berish sozlamalari — do'kon joylashuvi, 1 km narxi, bazaviy narx (`/delivery`)
- 📋 Mahsulotlar, 📦 buyurtmalar, 👤 adminlar ro'yxati
- 👑 Bosh adminlar: yangi admin qo'shish/o'chirish

## Diqqat
- `photo_url` maydoniga rasm havolasini kiritsangiz, mahsulot kartasida
  rasm ko'rinadi (hozircha admin panelda rasm yuklash botga emas,
  faqat URL orqali ishlaydi).
- Yetkazib berish narxi to'g'ri chiziq (havo yo'li) masofasi bo'yicha
  hisoblanadi — real yo'l uzunligidan biroz farq qilishi mumkin.
- Ishlab chiqarish (production) uchun `PUBLIC_BASE_URL`ni doimiy domenga
  o'tkazing va serverni `systemd`/`docker` orqali doimiy ishlaydigan
  qilib sozlang.
