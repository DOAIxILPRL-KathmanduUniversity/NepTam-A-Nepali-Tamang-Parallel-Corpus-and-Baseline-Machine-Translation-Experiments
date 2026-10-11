// Shared helpers for all studio pages.
const api = async (path, opts = {}) => {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
};

function toast(msg, kind = 'ok', ms = 3200) {
  let box = document.getElementById('toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, ms);
}

function fmtDur(sec) {
  sec = Math.round(sec || 0);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

const FLAG_LABELS = {
  silent: 'No speech detected', clipped: 'Clipping (too loud)', quiet: 'Too quiet',
  short: 'Very short', long: 'Very long', fast: 'Spoken very fast', slow: 'Spoken very slow',
};

function renderNav(active) {
  const nav = document.createElement('header');
  nav.className = 'nav';
  nav.innerHTML = `
    <a class="brand" href="/record"><span class="brand-dot">🎙</span><span>Nepali Audio Studio</span></a>
    <nav class="nav-links">
      <a href="/record" class="${active === 'record' ? 'active' : ''}">Record</a>
      <a href="/dashboard" class="${active === 'dashboard' ? 'active' : ''}">Dashboard</a>
      <a href="/review" class="${active === 'review' ? 'active' : ''}">Review</a>
    </nav>
    <div class="nav-progress"><span id="navCount" class="tnum">–</span>
      <div class="mini-bar"><span id="navBar" style="width:0%"></span></div></div>`;
  document.body.prepend(nav);
}

function updateNavProgress(recorded, total) {
  const c = document.getElementById('navCount'), b = document.getElementById('navBar');
  if (!c) return;
  c.textContent = `${recorded.toLocaleString()} / ${total.toLocaleString()}`;
  b.style.width = `${(recorded / total) * 100}%`;
}

// Prevent buttons from taking focus on click, so Space/Enter never "re-click" them.
document.addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
