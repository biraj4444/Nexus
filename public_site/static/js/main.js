/* NexusVault Public JS */

// ── Sidebar toggle ────────────────────────────────────────────────────────────
const sidebar  = document.getElementById('sidebar');
const overlay  = document.getElementById('overlay');
const toggleBtn= document.getElementById('sidebarToggle');

function openSidebar()  { sidebar?.classList.add('open');  overlay?.classList.add('show'); }
function closeSidebar() { sidebar?.classList.remove('open'); overlay?.classList.remove('show'); }

toggleBtn?.addEventListener('click', openSidebar);
overlay?.addEventListener('click', closeSidebar);

// ── Sidebar search (live filter) ──────────────────────────────────────────────
const sideSearch = document.getElementById('sideSearch');
sideSearch?.addEventListener('input', () => {
  const q = sideSearch.value.toLowerCase();
  document.querySelectorAll('.nav-item[data-label]').forEach(el => {
    el.style.display = el.dataset.label.toLowerCase().includes(q) ? '' : 'none';
  });
});

// ── Upload type tabs ──────────────────────────────────────────────────────────
document.querySelectorAll('.type-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.type-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.type-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('pane-' + target)?.classList.add('active');
    const inp = document.getElementById('typeInput');
    if (inp) inp.value = target;
  });
});

// ── Discussion reply toggle ───────────────────────────────────────────────────
document.querySelectorAll('.disc-reply-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const discId = btn.dataset.id;
    const form   = document.getElementById('reply-form-' + discId);
    if (!form) return;
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
  });
});

// ── Image lightbox ────────────────────────────────────────────────────────────
const lightbox = document.getElementById('lightbox');
const lbImg    = document.getElementById('lbImg');
document.querySelectorAll('.img-view').forEach(img => {
  img.addEventListener('click', () => {
    if (!lightbox || !lbImg) return;
    lbImg.src = img.src;
    lightbox.classList.add('show');
  });
});
document.getElementById('lbClose')?.addEventListener('click', () => lightbox?.classList.remove('show'));
lightbox?.addEventListener('click', e => { if (e.target === lightbox) lightbox.classList.remove('show'); });

// ── Flash auto-dismiss ────────────────────────────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => el.style.opacity = '0', 4000);
  setTimeout(() => el.remove(), 4400);
});

// ── File input preview ────────────────────────────────────────────────────────
const fileInput = document.getElementById('fileInput');
const filePreview = document.getElementById('filePreview');
fileInput?.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (!file || !filePreview) return;
  filePreview.textContent = `📎 ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
  filePreview.style.display = 'block';
});

// ── Copy link ─────────────────────────────────────────────────────────────────
document.querySelectorAll('.copy-link-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const url = btn.dataset.url;
    navigator.clipboard.writeText(url).then(() => {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = orig, 2000);
    });
  });
});

// ── Search form redirect ──────────────────────────────────────────────────────
document.querySelectorAll('.search-form-inline').forEach(form => {
  form.addEventListener('submit', e => {
    e.preventDefault();
    const q = form.querySelector('input[name=q]')?.value?.trim();
    if (q) window.location.href = '/search?q=' + encodeURIComponent(q);
  });
});

// ── Live stats polling ────────────────────────────────────────────────────────
function pollStats() {
  fetch('/api/stats').then(r => r.json()).then(data => {
    document.querySelectorAll('[data-stat]').forEach(el => {
      const key = el.dataset.stat;
      if (data[key] !== undefined) el.textContent = data[key].toLocaleString();
    });
  }).catch(() => {});
}
if (document.querySelector('[data-stat]')) {
  pollStats();
  setInterval(pollStats, 30000);
}
