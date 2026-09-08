// ── New Session Modal ─────────────────────────────────────────────────────

function openNewSessionModal() {
  document.getElementById('modalBackdrop').style.display = '';
  document.getElementById('newSessionModal').style.display = '';
  document.getElementById('ms-msg').textContent = '';
  // Clear repo pill selections so each open starts fresh
  document.querySelectorAll('#ms-repo-list .repo-pill').forEach(p => p.classList.remove('selected'));
}

function closeNewSessionModal() {
  document.getElementById('modalBackdrop').style.display = 'none';
  document.getElementById('newSessionModal').style.display = 'none';
}

async function submitNewSession() {
  const repos  = [...document.querySelectorAll('#ms-repo-list .repo-pill.selected')].map(el => el.dataset.repo);
  const agent  = document.getElementById('ms-agent')?.value;
  const bugId  = document.getElementById('ms-bugid')?.value?.trim() || undefined;
  const msgEl  = document.getElementById('ms-msg');
  const btn    = document.querySelector('#newSessionModal .btn-primary');

  if (!agent) {
    msgEl.textContent = 'Agent is required.';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Creating…';
  msgEl.textContent = '';

  try {
    const payload = { agent, repositories: repos };
    if (bugId) payload.bug_id = bugId;
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (r.ok) {
      const d = await r.json();
      closeNewSessionModal();
      window.location.href = `/sessions/${d.session_id}`;
    } else {
      const err = await r.json().catch(() => ({}));
      msgEl.textContent = err.detail || `Error ${r.status}`;
      btn.disabled = false;
      btn.textContent = 'Create Session';
    }
  } catch (e) {
    msgEl.textContent = 'Network error: ' + e.message;
    btn.disabled = false;
    btn.textContent = 'Create Session';
  }
}

// Close modal on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeNewSessionModal();
});

// ── Sidebar collapse ──────────────────────────────────────────────────────
const collapseBtn = document.getElementById('collapseBtn');
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');

if (collapseBtn && sidebar) {
  collapseBtn.addEventListener('click', () => {
    const collapsed = sidebar.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebar-collapsed', collapsed ? '1' : '0');
  });

  if (localStorage.getItem('sidebar-collapsed') === '1') {
    sidebar.classList.add('sidebar-collapsed');
  }
}
