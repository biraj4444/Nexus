/* NexusVault Admin JS */

// ── Type tabs ─────────────────────────────────────────────────────────────────
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

// ── Drop zone ─────────────────────────────────────────────────────────────────
document.querySelectorAll('.drop-zone').forEach(zone => {
  const input = zone.querySelector('input[type=file]') || document.getElementById('fileInput');
  zone.addEventListener('click', e => { if (e.target !== input) input?.click(); });
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('dragover');
    if (e.dataTransfer.files.length && input) {
      input.files = e.dataTransfer.files;
      updateFilePreview(input, zone);
    }
  });
  input?.addEventListener('change', () => updateFilePreview(input, zone));
});

function updateFilePreview(input, zone) {
  const file = input.files[0];
  if (!file) return;
  const preview = zone.querySelector('.dz-preview') || document.getElementById('dzPreview');
  if (preview) {
    preview.textContent = `📎 ${file.name} — ${(file.size/1024/1024).toFixed(2)} MB`;
    preview.style.display = 'block';
  }
}

// ── Approve / Feature inline toggle ──────────────────────────────────────────
document.querySelectorAll('[data-action="approve"]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const itemId = btn.dataset.id;
    const res = await fetch(`/item/${itemId}/approve`, { method:'POST' });
    const data = await res.json();
    if (data.ok) {
      btn.textContent = data.is_approved ? 'Unapprove' : 'Approve';
      const badge = document.getElementById('approved-badge-' + itemId);
      if (badge) {
        badge.textContent = data.is_approved ? 'YES' : 'NO';
        badge.className = 'badge ' + (data.is_approved ? 'badge-yes' : 'badge-no');
      }
      showToast(data.is_approved ? 'Item approved ✓' : 'Item unapproved', data.is_approved ? 'success' : 'info');
    }
  });
});

document.querySelectorAll('[data-action="feature"]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const itemId = btn.dataset.id;
    const res = await fetch(`/item/${itemId}/feature`, { method:'POST' });
    const data = await res.json();
    if (data.ok) {
      const badge = document.getElementById('featured-badge-' + itemId);
      if (badge) {
        badge.textContent = data.is_featured ? '★' : '☆';
        badge.style.color = data.is_featured ? 'var(--accent)' : 'var(--text-muted)';
      }
      showToast(data.is_featured ? 'Marked as featured ★' : 'Removed from featured', 'info');
    }
  });
});

// ── Delete confirm ────────────────────────────────────────────────────────────
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', e => {
    const msg = form.dataset.confirm || 'Are you sure?';
    if (!confirm(msg)) e.preventDefault();
  });
});

// ── Flash dismiss ─────────────────────────────────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => el.style.opacity = '0', 4000);
  setTimeout(() => el.remove(), 4400);
});

// ── Toast utility ─────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const container = document.querySelector('.flashes') || (() => {
    const d = document.createElement('div');
    d.className = 'flashes';
    document.body.appendChild(d);
    return d;
  })();
  const el = document.createElement('div');
  el.className = `flash flash-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.style.opacity = '0', 3000);
  setTimeout(() => el.remove(), 3400);
}

// ── Live stats polling ────────────────────────────────────────────────────────
function pollStats() {
  fetch('/api/stats').then(r => r.json()).then(data => {
    document.querySelectorAll('[data-stat]').forEach(el => {
      const key = el.dataset.stat;
      if (data[key] !== undefined) el.textContent = Number(data[key]).toLocaleString();
    });
  }).catch(() => {});
}
if (document.querySelector('[data-stat]')) {
  pollStats();
  setInterval(pollStats, 15000);
}

// ── Slug auto-generate from name ──────────────────────────────────────────────
const nameInput = document.getElementById('nameInput');
const slugInput = document.getElementById('slugInput');
if (nameInput && slugInput) {
  nameInput.addEventListener('input', () => {
    if (!slugInput._userEdited) {
      slugInput.value = nameInput.value.toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    }
  });
  slugInput.addEventListener('input', () => { slugInput._userEdited = true; });
}
