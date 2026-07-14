// script.js
// ------------------------------------------------------------------
// Bu fayl index.html sahifasini "jonlantiradi":
//   1) bot.py dagi HTTP API dan (/api/products) mahsulotlar ro'yxatini
//      fetch() orqali olib, ekranga chiqaradi.
//   2) Savat (cart) mantig'ini boshqaradi: qo'shish, o'chirish, summani
//      hisoblash.
//   3) Promokod kiritilganda /api/promocode/{code} ga so'rov yuborib,
//      chegirmani tekshiradi va umumiy summadan foizni ayiradi.
//   4) "Sotib olish" bosilganda buyurtma ma'lumotlarini (mahsulotlar,
//      narx, promokod) fetch() orqali /api/checkout ga POST qiladi -
//      bot shu yerdan buyurtmani o'qib, adminlarga xabar yuboradi.
// ------------------------------------------------------------------

// Telegram WebApp obyekti - foydalanuvchi ma'lumotlari va tema uchun
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand(); // sahifani to'liq ekranga yoyish
}

// API bazaviy manzili: script.js index.html bilan bir xil serverdan
// (bot.py dagi aiohttp) yuklangani uchun nisbiy yo'llardan foydalanamiz.
const API_BASE = ""; // masalan "/api/products" -> shu domenning o'zidan

// ------------------------------------------------------------------
// HOLAT (STATE)
// ------------------------------------------------------------------
let PRODUCTS = [];           // serverdan kelgan barcha mahsulotlar
let cart = {};                // { product_id: qty }
let appliedPromo = null;      // { code, discount_percent } yoki null

// ------------------------------------------------------------------
// DOM elementlari
// ------------------------------------------------------------------
const productsEl = document.getElementById("products");
const emptyStateEl = document.getElementById("empty-state");
const cartBarEl = document.getElementById("cart-bar");
const cartCountEl = document.getElementById("cart-count");
const finalPriceEl = document.getElementById("final-price");
const oldPriceEl = document.getElementById("old-price");
const promoInput = document.getElementById("promo-input");
const promoMessageEl = document.getElementById("promo-message");
const applyPromoBtn = document.getElementById("apply-promo-btn");
const phoneInput = document.getElementById("phone-input");
const phoneMessageEl = document.getElementById("phone-message");
const paymentCardsBlock = document.getElementById("payment-cards-block");
const paymentCardsListEl = document.getElementById("payment-cards-list");
const checkoutBtn = document.getElementById("checkout-btn");
const toastEl = document.getElementById("toast");

// ------------------------------------------------------------------
// 1) MAHSULOTLARNI YUKLASH
// ------------------------------------------------------------------
async function loadProducts() {
  try {
    const res = await fetch(`${API_BASE}/api/products`);
    PRODUCTS = await res.json();
  } catch (err) {
    console.error("Mahsulotlarni yuklashda xatolik:", err);
    PRODUCTS = [];
  }
  renderProducts();
}

// ------------------------------------------------------------------
// 1b) TO'LOV KARTALARINI YUKLASH (checkout paneli uchun)
// ------------------------------------------------------------------
async function loadPaymentCards() {
  try {
    const res = await fetch(`${API_BASE}/api/payment-cards`);
    const cards = await res.json();
    if (Array.isArray(cards) && cards.length > 0) {
      paymentCardsListEl.innerHTML = cards
        .map((c) => {
          const meta = [c.holder_name, c.bank_name].filter(Boolean).join(" · ");
          return `<div class="card-item">${c.card_number}${meta ? `<span class="card-meta">${meta}</span>` : ""}</div>`;
        })
        .join("");
      paymentCardsBlock.style.display = "block";
    } else {
      paymentCardsBlock.style.display = "none";
    }
  } catch (err) {
    console.error("To'lov kartalarini yuklashda xatolik:", err);
    paymentCardsBlock.style.display = "none";
  }
}

// Oddiy telefon raqami tekshiruvi: kamida 9 ta raqamdan iborat bo'lishi kerak
// (masalan +998901234567 yoki 901234567 ko'rinishida kiritish mumkin)
function isValidPhone(value) {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 9;
}

function renderProducts() {
  productsEl.innerHTML = "";

  if (!PRODUCTS.length) {
    emptyStateEl.style.display = "block";
    return;
  }
  emptyStateEl.style.display = "none";

  PRODUCTS.forEach((product) => {
    const card = document.createElement("div");
    card.className = "product-card";

    const hasSizes = getSizeList(product).length > 0;
    const qtyInCart = getTotalQtyForProduct(product.id);
    const sizesHint = hasSizes ? `<div class="sizes-hint">Razmer: ${getSizeList(product).join(", ")}</div>` : "";

    card.innerHTML = `
      <div class="img-placeholder" data-id="${product.id}">
        ${product.photo_url
          ? `<img src="${escapeAttr(product.photo_url)}" alt="${escapeHtml(product.name)}">`
          : "🛒"}
      </div>
      <div class="name" data-id="${product.id}">${escapeHtml(product.name)}</div>
      <div class="desc">${escapeHtml(product.description || "")}</div>
      ${sizesHint}
      <div class="price">${formatPrice(product.price)} so'm</div>
      <div class="card-actions">
        <button class="add-btn ${qtyInCart ? "in-cart" : ""}" data-id="${product.id}">
          ${qtyInCart ? `✓ Savatda (${qtyInCart})` : (hasSizes ? "Razmer tanlash" : "+ Savatga qo'shish")}
        </button>
        <button class="detail-btn" data-id="${product.id}">Batafsil</button>
      </div>
    `;

    productsEl.appendChild(card);
  });

  // "Savatga qo'shish / Razmer tanlash" tugmasi
  document.querySelectorAll(".add-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.id);
      const product = PRODUCTS.find((p) => p.id === id);
      if (getSizeList(product).length > 0) {
        openProductModal(id); // razmer bor - avval tanlatamiz
      } else {
        addToCart(id, ""); // razmer yo'q - to'g'ridan-to'g'ri qo'shamiz
      }
    });
  });

  // "Batafsil" tugmasi va rasm/nom bosilganda ham tafsilot ochiladi
  document.querySelectorAll(".detail-btn, .img-placeholder, .product-card .name").forEach((el) => {
    el.addEventListener("click", () => openProductModal(Number(el.dataset.id)));
  });
}

// Mahsulotning razmerlar ro'yxatini qaytaradi (bo'sh bo'lsa - razmer yo'q degani)
function getSizeList(product) {
  if (!product || !product.sizes) return [];
  return product.sizes.split(",").map((s) => s.trim()).filter(Boolean);
}

// Berilgan mahsulotning barcha razmerlar bo'yicha savatdagi umumiy sonini qaytaradi
function getTotalQtyForProduct(productId) {
  return Object.values(cart)
    .filter((item) => item.productId === productId)
    .reduce((sum, item) => sum + item.qty, 0);
}

// ------------------------------------------------------------------
// 2) SAVAT MANTIG'I
// ------------------------------------------------------------------
// cart obyektida har bir kalit "productId__size" ko'rinishida
// (razmer bo'lmasa size = ""), shunda bitta mahsulotning turli
// razmerlari savatda alohida qatorlar sifatida saqlanadi.
function cartKey(productId, size) {
  return `${productId}__${size || ""}`;
}

function addToCart(productId, size = "") {
  const key = cartKey(productId, size);
  if (!cart[key]) {
    cart[key] = { productId, size, qty: 0 };
  }
  cart[key].qty += 1;

  renderProducts();
  updateCartBar();
  showToast(size ? `Savatga qo'shildi ✅ (razmer: ${size})` : "Savatga qo'shildi ✅");
  tg?.HapticFeedback?.impactOccurred("light");
}

function getCartItems() {
  return Object.values(cart).map((entry) => {
    const product = PRODUCTS.find((p) => p.id === entry.productId);
    return {
      id: entry.productId,
      name: product?.name || "Noma'lum mahsulot",
      price: product?.price || 0,
      size: entry.size || "",
      qty: entry.qty,
    };
  });
}

function getCartTotal() {
  return getCartItems().reduce((sum, item) => sum + item.price * item.qty, 0);
}

function updateCartBar() {
  const items = getCartItems();
  const totalQty = items.reduce((sum, i) => sum + i.qty, 0);
  const total = getCartTotal();

  cartCountEl.textContent = totalQty;

  if (totalQty > 0) {
    cartBarEl.classList.add("visible");
  } else {
    cartBarEl.classList.remove("visible");
  }

  // Promokod mavjud bo'lsa - chegirmalangan summani ko'rsatamiz
  if (appliedPromo) {
    const discounted = total * (1 - appliedPromo.discount_percent / 100);
    oldPriceEl.style.display = "inline";
    oldPriceEl.textContent = `${formatPrice(total)} so'm`;
    finalPriceEl.textContent = `${formatPrice(discounted)} so'm`;
  } else {
    oldPriceEl.style.display = "none";
    finalPriceEl.textContent = `${formatPrice(total)} so'm`;
  }

  checkoutBtn.disabled = totalQty === 0;
}

// ------------------------------------------------------------------
// 3) PROMOKOD MANTIG'I
// ------------------------------------------------------------------
applyPromoBtn.addEventListener("click", async () => {
  const code = promoInput.value.trim().toUpperCase();
  if (!code) {
    setPromoMessage("Promokodni kiriting", "err");
    return;
  }

  applyPromoBtn.disabled = true;
  applyPromoBtn.textContent = "...";

  try {
    const res = await fetch(`${API_BASE}/api/promocode/${encodeURIComponent(code)}`);
    const data = await res.json();

    if (data.valid) {
      appliedPromo = { code, discount_percent: data.discount_percent };
      setPromoMessage(`✅ Promokod qabul qilindi: -${data.discount_percent}%`, "ok");
      tg?.HapticFeedback?.notificationOccurred("success");
    } else {
      appliedPromo = null;
      setPromoMessage("❌ Promokod noto'g'ri yoki muddati o'tgan", "err");
      tg?.HapticFeedback?.notificationOccurred("error");
    }
  } catch (err) {
    console.error("Promokodni tekshirishda xatolik:", err);
    setPromoMessage("❌ Xatolik yuz berdi, qayta urinib ko'ring", "err");
  } finally {
    applyPromoBtn.disabled = false;
    applyPromoBtn.textContent = "Qo'llash";
    updateCartBar();
  }
});

function setPromoMessage(text, type) {
  promoMessageEl.textContent = text;
  promoMessageEl.className = type; // "ok" yoki "err"
}

// ------------------------------------------------------------------
// 4) "SOTIB OLISH" - buyurtmani botga yuborish
// ------------------------------------------------------------------
checkoutBtn.addEventListener("click", async () => {
  const items = getCartItems();
  if (!items.length) return;

  const phone = phoneInput.value.trim();
  if (!isValidPhone(phone)) {
    phoneMessageEl.textContent = "❗️ Telefon raqamingizni to'g'ri kiriting (masalan +998901234567)";
    phoneInput.classList.add("err");
    phoneInput.focus();
    tg?.HapticFeedback?.notificationOccurred("error");
    return;
  }
  phoneMessageEl.textContent = "";
  phoneInput.classList.remove("err");

  // Botni Telegram ilovasi ichida ochish shart - initData shu yerdan keladi
  // va server tomonda foydalanuvchini tasdiqlash uchun ishlatiladi.
  if (!tg || !tg.initData) {
    showToast("❗️ Botni Telegram ilovasi ichida oching.");
    return;
  }

  // Eslatma: narx va mahsulot nomini serverga yubormaymiz - faqat
  // id/size/qty. Yakuniy narxni server bazadagi haqiqiy narxlardan
  // qayta hisoblab chiqadi (brauzerdan narxni "buzib" yuborish oldini olish uchun).
  const orderPayload = {
    items: items.map((i) => ({ id: i.id, size: i.size, qty: i.qty })),
    promo_code: appliedPromo ? appliedPromo.code : null,
    phone: phone,
    init_data: tg.initData,
  };

  checkoutBtn.disabled = true;
  checkoutBtn.textContent = "Yuborilmoqda...";

  try {
    const res = await fetch(`${API_BASE}/api/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(orderPayload),
    });
    const data = await res.json();

    if (data.ok) {
      showToast("✅ Buyurtma qabul qilindi!");
      tg?.HapticFeedback?.notificationOccurred("success");

      // Savatni tozalaymiz
      cart = {};
      appliedPromo = null;
      promoInput.value = "";
      phoneInput.value = "";
      setPromoMessage("", "");
      renderProducts();
      updateCartBar();

      // WebApp oynasini yopamiz. Eslatma: buyurtma FAQAT shu fetch()
      // orqali bir marta yuboriladi - qo'shimcha tg.sendData() chaqirilmaydi,
      // aks holda bot ikkinchi marta xuddi shu buyurtmani yaratib qo'yardi.
      setTimeout(() => tg?.close(), 900);
    } else if (data.error === "auth_failed") {
      showToast("❗️ Foydalanuvchini tasdiqlab bo'lmadi. Botni qayta oching.");
    } else if (data.error === "phone_required") {
      showToast("❗️ Telefon raqamingizni kiriting.");
    } else {
      throw new Error(data.error || "unknown_error");
    }
  } catch (err) {
    console.error("Buyurtma yuborishda xatolik:", err);
    showToast("❌ Xatolik yuz berdi. Qayta urinib ko'ring.");
  } finally {
    checkoutBtn.disabled = false;
    checkoutBtn.textContent = "Sotib olish";
  }
});

// ------------------------------------------------------------------
// YORDAMCHI FUNKSIYALAR
// ------------------------------------------------------------------
function formatPrice(value) {
  return Math.round(value).toLocaleString("uz-UZ");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// Atribut ichiga (masalan src="...") qo'yish uchun qo'shtirnoqni ham escape qiladi
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}

let toastTimeout;
function showToast(text) {
  toastEl.textContent = text;
  toastEl.classList.add("show");
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toastEl.classList.remove("show"), 2200);
}

// ------------------------------------------------------------------
// 5) MAHSULOT TAFSILOTI / RAZMER TANLASH MODALI
// ------------------------------------------------------------------
const modalOverlay = document.getElementById("modal-overlay");
const productModal = document.getElementById("product-modal");
const modalImg = document.getElementById("modal-img");
const modalName = document.getElementById("modal-name");
const modalPrice = document.getElementById("modal-price");
const modalDesc = document.getElementById("modal-desc");
const modalSizesWrap = document.getElementById("modal-sizes-wrap");
const modalSizesEl = document.getElementById("modal-sizes");
const modalAddBtn = document.getElementById("modal-add-btn");
const modalCloseBtn = document.getElementById("modal-close-btn");

let modalProductId = null;
let modalSelectedSize = null;

function openProductModal(productId) {
  const product = PRODUCTS.find((p) => p.id === productId);
  if (!product) return;

  modalProductId = productId;
  modalSelectedSize = null;

  modalImg.innerHTML = product.photo_url
    ? `<img src="${escapeAttr(product.photo_url)}" alt="${escapeHtml(product.name)}">`
    : "🛒";
  modalName.textContent = product.name;
  modalPrice.textContent = `${formatPrice(product.price)} so'm`;
  modalDesc.textContent = product.description || "Tavsif kiritilmagan.";

  const sizes = getSizeList(product);
  if (sizes.length > 0) {
    modalSizesWrap.style.display = "block";
    modalSizesEl.innerHTML = sizes
      .map((s) => `<button class="size-chip" data-size="${escapeHtml(s)}">${escapeHtml(s)}</button>`)
      .join("");
    document.querySelectorAll(".size-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        modalSelectedSize = chip.dataset.size;
        document.querySelectorAll(".size-chip").forEach((c) => c.classList.remove("selected"));
        chip.classList.add("selected");
      });
    });
  } else {
    modalSizesWrap.style.display = "none";
    modalSizesEl.innerHTML = "";
  }

  modalOverlay.classList.add("visible");
  productModal.classList.add("visible");
}

function closeProductModal() {
  modalOverlay.classList.remove("visible");
  productModal.classList.remove("visible");
  modalProductId = null;
  modalSelectedSize = null;
}

modalCloseBtn.addEventListener("click", closeProductModal);
modalOverlay.addEventListener("click", closeProductModal);

modalAddBtn.addEventListener("click", () => {
  if (modalProductId === null) return;
  const product = PRODUCTS.find((p) => p.id === modalProductId);
  const sizes = getSizeList(product);

  if (sizes.length > 0 && !modalSelectedSize) {
    showToast("❗️ Avval razmerni tanlang");
    tg?.HapticFeedback?.notificationOccurred("error");
    return;
  }

  addToCart(modalProductId, modalSelectedSize || "");
  closeProductModal();
});

// ------------------------------------------------------------------
// ISHGA TUSHIRISH
// ------------------------------------------------------------------
loadProducts();
loadPaymentCards();
updateCartBar();
