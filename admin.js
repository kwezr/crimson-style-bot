// admin.js
// ------------------------------------------------------------------
// Veb admin panelning mantig'i. Har bir so'rov "X-Init-Data" headerida
// Telegram WebApp initData sini yuboradi - bot.py shu orqali admin
// ekanligini tekshiradi (require_admin()).
// ------------------------------------------------------------------

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const API_BASE = "";
const INIT_DATA = tg?.initData || "";

let IS_SUPER_ADMIN = false;

const toastEl = document.getElementById("toast");
function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), 2200);
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": INIT_DATA,
      ...(options.headers || {}),
    },
  });
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (res.status === 403) {
    showToast("⛔️ Ruxsat yo'q");
  }
  return { status: res.status, data };
}

// ------------------------------------------------------------------
// TABLAR
// ------------------------------------------------------------------
const tabButtons = document.querySelectorAll("#tabs button");
const sections = document.querySelectorAll(".section");

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    sections.forEach((s) => s.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");

    if (btn.dataset.tab === "products") loadProducts();
    if (btn.dataset.tab === "promos") loadPromos();
    if (btn.dataset.tab === "cards") loadCards();
    if (btn.dataset.tab === "orders") loadOrders();
    if (btn.dataset.tab === "delivery") loadDelivery();
    if (btn.dataset.tab === "admins") loadAdmins();
  });
});

// ------------------------------------------------------------------
// MAHSULOTLAR
// ------------------------------------------------------------------
async function loadProducts() {
  const listEl = document.getElementById("products-list");
  listEl.innerHTML = `<div class="empty">Yuklanmoqda...</div>`;
  const { data } = await apiFetch("/api/admin/products");
  if (!Array.isArray(data) || data.length === 0) {
    listEl.innerHTML = `<div class="empty">Hozircha mahsulot yo'q</div>`;
    return;
  }
  listEl.innerHTML = data
    .map(
      (p) => `
      <div class="card">
        <div class="title">${p.name}${p.is_active ? "" : " <span class='muted'>(faol emas)</span>"}</div>
        ${p.description ? `<div class="muted">${p.description}</div>` : ""}
        ${p.sizes ? `<div class="muted">Razmerlar: ${p.sizes}</div>` : ""}
        <div class="row">
          <span class="price">${Math.round(p.price)} so'm</span>
          <span>
            <button class="btn btn-outline" data-action="edit-price" data-id="${p.id}" data-price="${p.price}">✏️ Narx</button>
            <button class="btn btn-danger" data-action="delete-product" data-id="${p.id}">🗑</button>
          </span>
        </div>
      </div>`
    )
    .join("");

  listEl.querySelectorAll('[data-action="edit-price"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const newPrice = prompt("Yangi narxni kiriting (so'm):", btn.dataset.price);
      if (newPrice === null) return;
      const val = parseFloat(newPrice);
      if (!val || val <= 0) return showToast("❗️ Narx noto'g'ri");
      const { data } = await apiFetch(`/api/admin/products/${btn.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ price: val }),
      });
      if (data?.ok) {
        showToast("✅ Narx yangilandi");
        loadProducts();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });

  listEl.querySelectorAll('[data-action="delete-product"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Mahsulotni o'chirishga ishonchingiz komilmi?")) return;
      const { data } = await apiFetch(`/api/admin/products/${btn.dataset.id}`, { method: "DELETE" });
      if (data?.ok) {
        showToast("✅ O'chirildi");
        loadProducts();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
}

document.getElementById("p-add-btn").addEventListener("click", async () => {
  const name = document.getElementById("p-name").value.trim();
  const price = parseFloat(document.getElementById("p-price").value);
  const sizes = document.getElementById("p-sizes").value.trim();
  const photo_url = document.getElementById("p-photo").value.trim();
  const description = document.getElementById("p-desc").value.trim();

  if (!name || !price || price <= 0) {
    return showToast("❗️ Nomi va narxini to'g'ri kiriting");
  }

  const { data } = await apiFetch("/api/admin/products", {
    method: "POST",
    body: JSON.stringify({ name, price, sizes, photo_url, description }),
  });
  if (data?.ok) {
    showToast("✅ Mahsulot qo'shildi");
    document.getElementById("p-name").value = "";
    document.getElementById("p-price").value = "";
    document.getElementById("p-sizes").value = "";
    document.getElementById("p-photo").value = "";
    document.getElementById("p-desc").value = "";
    loadProducts();
  } else {
    showToast("❌ Xatolik yuz berdi");
  }
});

// ------------------------------------------------------------------
// PROMOKODLAR
// ------------------------------------------------------------------
async function loadPromos() {
  const listEl = document.getElementById("promos-list");
  listEl.innerHTML = `<div class="empty">Yuklanmoqda...</div>`;
  const { data } = await apiFetch("/api/admin/promocodes");
  if (!Array.isArray(data) || data.length === 0) {
    listEl.innerHTML = `<div class="empty">Hozircha promokod yo'q</div>`;
    return;
  }
  listEl.innerHTML = data
    .map(
      (p) => `
      <div class="card">
        <div class="row">
          <span class="title">${p.code} — ${p.discount_percent}%</span>
          <button class="btn btn-danger" data-action="delete-promo" data-code="${p.code}">🗑</button>
        </div>
      </div>`
    )
    .join("");

  listEl.querySelectorAll('[data-action="delete-promo"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`"${btn.dataset.code}" promokodini o'chirishga ishonchingiz komilmi?`)) return;
      const { data } = await apiFetch(`/api/admin/promocodes/${encodeURIComponent(btn.dataset.code)}`, {
        method: "DELETE",
      });
      if (data?.ok) {
        showToast("✅ O'chirildi");
        loadPromos();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
}

document.getElementById("promo-add-btn").addEventListener("click", async () => {
  const code = document.getElementById("promo-code").value.trim().toUpperCase();
  const discount_percent = parseInt(document.getElementById("promo-percent").value, 10);

  if (!code || !discount_percent || discount_percent <= 0 || discount_percent > 100) {
    return showToast("❗️ Kod va foizni to'g'ri kiriting");
  }

  const { data } = await apiFetch("/api/admin/promocodes", {
    method: "POST",
    body: JSON.stringify({ code, discount_percent }),
  });
  if (data?.ok) {
    showToast("✅ Promokod qo'shildi");
    document.getElementById("promo-code").value = "";
    document.getElementById("promo-percent").value = "";
    loadPromos();
  } else if (data?.error === "already_exists") {
    showToast("❗️ Bu kod allaqachon mavjud");
  } else {
    showToast("❌ Xatolik yuz berdi");
  }
});

// ------------------------------------------------------------------
// TO'LOV KARTALARI
// ------------------------------------------------------------------
async function loadCards() {
  const listEl = document.getElementById("cards-list");
  listEl.innerHTML = `<div class="empty">Yuklanmoqda...</div>`;
  const { data } = await apiFetch("/api/admin/cards");
  if (!Array.isArray(data) || data.length === 0) {
    listEl.innerHTML = `<div class="empty">Hozircha karta yo'q</div>`;
    return;
  }
  listEl.innerHTML = data
    .map(
      (c) => `
      <div class="card">
        <div class="row">
          <div>
            <div class="title">${c.card_number_display}</div>
            <div class="muted">${[c.holder_name, c.bank_name].filter(Boolean).join(" · ") || "-"}</div>
          </div>
          <button class="btn btn-danger" data-action="delete-card" data-id="${c.id}">🗑</button>
        </div>
      </div>`
    )
    .join("");

  listEl.querySelectorAll('[data-action="delete-card"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Kartani o'chirishga ishonchingiz komilmi?")) return;
      const { data } = await apiFetch(`/api/admin/cards/${btn.dataset.id}`, { method: "DELETE" });
      if (data?.ok) {
        showToast("✅ O'chirildi");
        loadCards();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
}

document.getElementById("card-add-btn").addEventListener("click", async () => {
  const card_number = document.getElementById("card-number").value.trim();
  const holder_name = document.getElementById("card-holder").value.trim();
  const bank_name = document.getElementById("card-bank").value.trim();

  const digits = card_number.replace(/\D/g, "");
  if (digits.length < 12) {
    return showToast("❗️ Karta raqami noto'g'ri");
  }

  const { data } = await apiFetch("/api/admin/cards", {
    method: "POST",
    body: JSON.stringify({ card_number, holder_name, bank_name }),
  });
  if (data?.ok) {
    showToast("✅ Karta qo'shildi");
    document.getElementById("card-number").value = "";
    document.getElementById("card-holder").value = "";
    document.getElementById("card-bank").value = "";
    loadCards();
  } else {
    showToast("❌ Xatolik yuz berdi");
  }
});

// ------------------------------------------------------------------
// BUYURTMALAR
// ------------------------------------------------------------------
const STATUS_LABELS = {
  new: { text: "Kutilmoqda", cls: "status-new" },
  confirmed: { text: "Tasdiqlangan", cls: "status-confirmed" },
  cancelled: { text: "Bekor qilingan", cls: "status-cancelled" },
};

async function loadOrders() {
  const listEl = document.getElementById("orders-list");
  listEl.innerHTML = `<div class="empty">Yuklanmoqda...</div>`;
  const { data } = await apiFetch("/api/admin/orders?limit=50");
  if (!Array.isArray(data) || data.length === 0) {
    listEl.innerHTML = `<div class="empty">Hozircha buyurtma yo'q</div>`;
    return;
  }
  listEl.innerHTML = data
    .map((o) => {
      const status = STATUS_LABELS[o.status] || STATUS_LABELS.new;
      const itemsText = (o.items || [])
        .map((i) => `${i.name}${i.size ? ` [${i.size}]` : ""} x${i.qty}`)
        .join(", ");
      const actions =
        o.status === "new"
          ? `<button class="btn btn-ok" data-action="confirm-order" data-id="${o.id}">✅ Tasdiqlash</button>
             <button class="btn btn-danger" data-action="cancel-order" data-id="${o.id}">❌ Bekor qilish</button>`
          : "";
      return `
      <div class="card">
        <div class="row">
          <span class="title">Buyurtma #${o.id}</span>
          <span class="status-badge ${status.cls}">${status.text}</span>
        </div>
        <div class="muted" style="margin-top:6px;">${itemsText}</div>
        ${o.phone ? `<div class="muted">📞 ${o.phone}</div>` : ""}
        <div class="row">
          <span class="price">${Math.round(o.final_price)} so'm</span>
          <span>${actions}</span>
        </div>
      </div>`;
    })
    .join("");

  listEl.querySelectorAll('[data-action="confirm-order"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const { data } = await apiFetch(`/api/admin/orders/${btn.dataset.id}/confirm`, { method: "POST" });
      if (data?.ok) {
        showToast("✅ Tasdiqlandi");
        loadOrders();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
  listEl.querySelectorAll('[data-action="cancel-order"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const { data } = await apiFetch(`/api/admin/orders/${btn.dataset.id}/cancel`, { method: "POST" });
      if (data?.ok) {
        showToast("✅ Bekor qilindi");
        loadOrders();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
}

// ------------------------------------------------------------------
// YETKAZIB BERISH SOZLAMALARI
// ------------------------------------------------------------------
async function loadDelivery() {
  const { data } = await apiFetch("/api/admin/delivery");
  if (!data) return;
  document.getElementById("d-price-km").value = data.price_per_km ?? "";
  document.getElementById("d-base-fee").value = data.base_delivery_fee ?? "";

  const infoEl = document.getElementById("delivery-info");
  if (data.shop_lat && data.shop_lon) {
    infoEl.innerHTML = `<div class="muted">📍 Do'kon joylashuvi: ${data.shop_lat}, ${data.shop_lon}</div>`;
  } else {
    infoEl.innerHTML = `<div class="muted">📍 Do'kon joylashuvi hali sozlanmagan (bot ichida /delivery orqali sozlang)</div>`;
  }
}

document.getElementById("delivery-save-btn").addEventListener("click", async () => {
  const price_per_km = parseFloat(document.getElementById("d-price-km").value);
  const base_delivery_fee = parseFloat(document.getElementById("d-base-fee").value);
  if (isNaN(price_per_km) || isNaN(base_delivery_fee)) {
    return showToast("❗️ Qiymatlarni to'g'ri kiriting");
  }
  const { data } = await apiFetch("/api/admin/delivery", {
    method: "POST",
    body: JSON.stringify({ price_per_km, base_delivery_fee }),
  });
  if (data?.ok) {
    showToast("✅ Saqlandi");
  } else {
    showToast("❌ Xatolik yuz berdi");
  }
});

// ------------------------------------------------------------------
// ADMINLAR
// ------------------------------------------------------------------
async function loadAdmins() {
  const listEl = document.getElementById("admins-list");
  listEl.innerHTML = `<div class="empty">Yuklanmoqda...</div>`;
  document.getElementById("admin-add-box").style.display = IS_SUPER_ADMIN ? "block" : "none";

  const { data } = await apiFetch("/api/admin/admins");
  if (!data) {
    listEl.innerHTML = `<div class="empty">Yuklab bo'lmadi</div>`;
    return;
  }

  const superRows = (data.super_admin_ids || [])
    .map((id) => `<div class="card"><div class="row"><span>👑 ${id}</span><span class="muted">bosh admin</span></div></div>`)
    .join("");

  const adminRows = (data.admins || [])
    .map(
      (a) => `
      <div class="card">
        <div class="row">
          <span>${a.user_id}${a.username ? ` (@${a.username})` : ""}</span>
          ${IS_SUPER_ADMIN ? `<button class="btn btn-danger" data-action="remove-admin" data-id="${a.user_id}">🗑</button>` : ""}
        </div>
      </div>`
    )
    .join("");

  listEl.innerHTML = superRows + adminRows || `<div class="empty">Adminlar topilmadi</div>`;

  listEl.querySelectorAll('[data-action="remove-admin"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Adminni o'chirishga ishonchingiz komilmi?")) return;
      const { data } = await apiFetch(`/api/admin/admins/${btn.dataset.id}`, { method: "DELETE" });
      if (data?.ok) {
        showToast("✅ O'chirildi");
        loadAdmins();
      } else {
        showToast("❌ Xatolik yuz berdi");
      }
    });
  });
}

document.getElementById("admin-add-btn").addEventListener("click", async () => {
  const user_id = parseInt(document.getElementById("admin-new-id").value, 10);
  if (!user_id) return showToast("❗️ user_id ni to'g'ri kiriting");

  const { data } = await apiFetch("/api/admin/admins", {
    method: "POST",
    body: JSON.stringify({ user_id }),
  });
  if (data?.ok) {
    showToast("✅ Admin qo'shildi");
    document.getElementById("admin-new-id").value = "";
    loadAdmins();
  } else {
    showToast("❌ Xatolik yuz berdi");
  }
});

// ------------------------------------------------------------------
// ISHGA TUSHIRISH: avval admin ekanligini tekshiramiz
// ------------------------------------------------------------------
(async function init() {
  if (!INIT_DATA) {
    document.getElementById("denied").style.display = "block";
    return;
  }
  const { data } = await apiFetch("/api/admin/check");
  if (!data?.ok) {
    document.getElementById("denied").style.display = "block";
    return;
  }
  IS_SUPER_ADMIN = !!data.is_super_admin;
  document.getElementById("app-root").style.display = "block";
  loadProducts();
})();
