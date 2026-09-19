/* mock/shared/app.js — shared mock runtime: sidebar renderer, inline SVG icons,
   light/dark toggle, toast, tabs, modal, and drawer helpers. No real logic.
   Each app sets window.MOCK_APP (brand + nav) in its own nav.js before this file. */

const APP = window.MOCK_APP || { kind: "user", brand: { name: "Greenlight AI" }, nav: [] };

const ICONS = {
  logo: '<path d="M12 2 3 6v6c0 5 3.8 9.4 9 10 5.2-.6 9-5 9-10V6z"/><path d="m9 12 2 2 4-4"/>',
  runs: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  review: '<path d="M9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  report: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
  stats: '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  config: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  template: '<path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><rect width="8" height="6" x="2" y="12" rx="1"/>',
  check: '<path d="M21.8 10A10 10 0 1 1 17 3.3"/><path d="m9 11 3 3L22 4"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  doc: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  json: '<path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/>',
  sheet: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  xcircle: '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
  checkcircle: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  back: '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
  refresh: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
  edit: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  sparkle: '<path d="m12 3 1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9Z"/><path d="M19 3v4"/><path d="M21 5h-4"/>',
  eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.5 13.5 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>',
  flask: '<path d="M10 2v7.5L4.5 19a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9.5V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  admin: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  filter: '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  git: '<circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/>',
  tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  wand: '<path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/><path d="m14 7 3 3"/><path d="M5 6v4"/><path d="M19 14v4"/><path d="M10 2v2"/><path d="M7 8H3"/><path d="M21 16h-4"/><path d="M11 3H9"/>',
};

function icon(name, cls) {
  return (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    (cls ? ' class="' + cls + '"' : "") + ">" +
    (ICONS[name] || "") +
    "</svg>"
  );
}
window.icon = icon;

/* ---- sidebar ---- */
function renderSidebar() {
  const el = document.getElementById("sidebar");
  if (!el) return;
  const active = document.body.dataset.page;
  const items = APP.nav
    .map((n) => {
      const count = n.count ? '<span class="badge badge-destructive count">' + n.count + "</span>" : "";
      return (
        '<a class="nav-item' + (n.page === active ? " active" : "") + '" href="' + n.href + '">' +
        icon(n.icon) + "<span>" + n.label + "</span>" + count + "</a>"
      );
    })
    .join("");
  const other =
    APP.kind === "admin"
      ? '<a class="link" href="../user-ui/index.html">→ Open user-ui</a>'
      : '<a class="link" href="../admin-ui/index.html">→ Open admin-ui</a>';
  el.className = "sidebar";
  el.innerHTML =
    '<div class="brand"><div class="brand-mark">' + icon("logo") + "</div><div>" +
    '<div class="brand-name">' + APP.brand.name + "</div>" +
    '<div class="brand-tagline">' + APP.brand.tagline + "</div>" +
    '<div class="brand-sub">' + APP.brand.subtitle + "</div></div></div>" +
    '<span class="app-chip ' + APP.kind + '">' + icon(APP.kind === "admin" ? "admin" : "user") + " " +
    (APP.kind === "admin" ? "admin-ui · :3001" : "user-ui · :3000") + "</span>" +
    '<div class="menu-label">Menu</div>' +
    '<nav class="nav">' + items + "</nav>" +
    '<div class="sidebar-footer">' +
    '<div class="flex"><span>Mock preview · no backend</span>' +
    '<button class="icon-btn" id="themeBtn" title="Toggle light / dark"></button></div>' +
    '<div class="flex">' + other + '<a class="link" href="../index.html">Launcher</a></div>' +
    "</div>";
  document.getElementById("themeBtn").addEventListener("click", toggleTheme);
  syncThemeIcon();
}

/* ---- theme ---- */
function applyTheme(dark) {
  document.documentElement.classList.toggle("dark", dark);
  try { localStorage.setItem("greenlight-ai-mock-theme", dark ? "dark" : "light"); } catch (e) { /* file:// */ }
  syncThemeIcon();
}
function toggleTheme() { applyTheme(!document.documentElement.classList.contains("dark")); }
function syncThemeIcon() {
  document.querySelectorAll("#themeBtn, [data-theme-btn]").forEach((btn) => {
    btn.innerHTML = icon(document.documentElement.classList.contains("dark") ? "sun" : "moon");
  });
}
function initTheme() {
  let dark = false;
  try { dark = localStorage.getItem("greenlight-ai-mock-theme") === "dark"; } catch (e) { /* ignore */ }
  if (dark) document.documentElement.classList.add("dark");
}
window.toggleTheme = toggleTheme;

/* ---- toast ---- */
let toastTimer;
function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2400);
}
window.toast = toast;
window.mockToast = toast;
window.mock = function (what) { toast((what || "Action") + " (mock — nothing happens)"); };

/* ---- tabs: <button class="tab" data-tab="x"> + <div class="tab-panel" data-panel="x"> ---- */
function initTabs() {
  document.querySelectorAll(".tabs").forEach((bar) => {
    bar.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const scope = bar.parentElement;
        bar.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t === tab));
        scope.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("on", p.dataset.panel === tab.dataset.tab));
      });
    });
  });
}
window.showTab = function (name) {
  const tab = document.querySelector('.tab[data-tab="' + name + '"]');
  if (tab) tab.click();
};

/* ---- modal ---- */
window.openModal = function (id) { const m = document.getElementById(id); if (m) m.classList.add("open"); };
window.closeModal = function (id) { const m = document.getElementById(id); if (m) m.classList.remove("open"); };
document.addEventListener("click", (e) => {
  if (e.target.classList && e.target.classList.contains("modal")) e.target.classList.remove("open");
});

/* ---- drawer ---- */
window.openDrawer = function () {
  const d = document.getElementById("drawer"), s = document.getElementById("scrim");
  if (d) d.classList.add("open");
  if (s) s.classList.add("open");
};
window.closeDrawer = function () {
  const d = document.getElementById("drawer"), s = document.getElementById("scrim");
  if (d) d.classList.remove("open");
  if (s) s.classList.remove("open");
  document.querySelectorAll(".finding.open").forEach((f) => f.classList.remove("open"));
};

/* ---- switches ---- */
function initSwitches() {
  document.querySelectorAll(".switch").forEach((sw) => {
    sw.addEventListener("click", () => {
      sw.classList.toggle("on");
      toast((sw.dataset.label || "Setting") + (sw.classList.contains("on") ? " enabled" : " disabled") + " (mock)");
    });
  });
}

/* ---- drop zones ---- */
function initDrops() {
  document.querySelectorAll(".drop").forEach((z) => {
    ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.remove("over"); }));
    z.addEventListener("drop", () => toast("File received (mock — nothing is uploaded)"));
    z.addEventListener("click", () => toast("File picker would open here (mock)"));
  });
}

/* Replace <span data-icon="play"></span> placeholders with SVGs. */
function hydrateIcons() {
  document.querySelectorAll("[data-icon]").forEach((e) => { e.innerHTML = icon(e.getAttribute("data-icon")); });
}

initTheme();
document.addEventListener("DOMContentLoaded", () => {
  renderSidebar();
  hydrateIcons();
  initTabs();
  initSwitches();
  initDrops();
  syncThemeIcon();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeDrawer(); document.querySelectorAll(".modal.open").forEach((m) => m.classList.remove("open")); }
  });
});
