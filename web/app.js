import { t } from './i18n.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  route: 'home',
  lang: 'en',
  preset: null,
  pack: {
    name: '',
    paths: [],
    output: '',
    sensitive: [],
    sensitiveAllow: {},
    excluded: [],
    scan: null,
    jobId: null,
    job: null,
  },
  meta: null,
};

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function api(path, opts={}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers||{}) },
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return await r.json();
  return await r.text();
}

function clampStr(s, n=64) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n-1) + '…' : s;
}

function toastKey(key, vars={}, kind='info') {
  return toast(t(state.lang, key, vars), kind);
}

function toast(msg, kind='info') {
  const el = document.createElement('div');
  el.className = `pointer-events-auto px-4 py-3 rounded-xl border text-sm shadow-lg backdrop-blur bg-slate-900/70 ${
    kind==='error' ? 'border-red-800 text-red-200' :
    kind==='warn' ? 'border-amber-800 text-amber-200' :
    'border-slate-700 text-slate-200'
  }`;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.classList.add('opacity-0'); el.classList.add('translate-y-1'); }, 2400);
  setTimeout(() => el.remove(), 3100);
}

function setRoute(route) {
  state.route = route;
  render();
}

function openPalette() {
  $('#palette').classList.remove('hidden');
  $('#paletteOverlay').classList.remove('hidden');
  $('#paletteInput').value = '';
  $('#paletteInput').focus();
  renderPalette();
}

function closePalette() {
  $('#palette').classList.add('hidden');
  $('#paletteOverlay').classList.add('hidden');
}

function renderPalette() {
  const q = ($('#paletteInput').value || '').toLowerCase();
  const items = [
    { label: 'Home', route: 'home', k: 'g h' },
    { label: 'Pack (Wizard)', route: 'pack', k: 'p' },
    { label: 'Apply (Wizard)', route: 'apply', k: 'a' },
    { label: 'Inspect', route: 'inspect', k: 'i' },
    { label: 'Doctor', route: 'doctor', k: 'd' },
    { label: 'Settings', route: 'settings', k: 's' },
  ].filter(it => it.label.toLowerCase().includes(q) || it.k.includes(q));

  const ul = $('#paletteItems');
  ul.innerHTML = '';
  for (const it of items) {
    const li = document.createElement('button');
    li.className = 'w-full text-left px-3 py-2 rounded-lg hover:bg-slate-800/70 border border-transparent hover:border-slate-700 transition';
    li.innerHTML = `<div class="flex items-center justify-between"><div class="text-slate-100">${it.label}</div><div class="text-xs text-slate-400">${it.k}</div></div>`;
    li.addEventListener('click', () => { closePalette(); setRoute(it.route); });
    ul.appendChild(li);
  }
}

function render() {
  $$('#view > section').forEach(s => s.classList.add('hidden'));
  $('#navTitle').textContent = state.route === 'home' ? 'Dashboard' : state.route;
  $('#route-'+state.route)?.classList.remove('hidden');

  // active nav
  $$('.navbtn').forEach(b => {
    b.classList.toggle('bg-slate-800/70', b.dataset.route === state.route);
    b.classList.toggle('border-slate-700', b.dataset.route === state.route);
  });

  if (state.route === 'doctor') renderDoctor();
  if (state.route === 'settings') renderSettings();
  if (state.route === 'pack') renderPackWizard();
}

async function renderDoctor() {
  const pre = $('#doctorOut');
  pre.textContent = 'loading…';
  try {
    const data = await api('/api/doctor');
    pre.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    pre.textContent = String(e);
  }
}

async function renderSettings() {
  const pre = $('#settingsOut');
  pre.textContent = 'loading…';
  try {
    const data = await api('/api/settings');
    pre.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    pre.textContent = String(e);
  }
}

function renderPackWizard() {
  // step visibility
  const step = Number($('#packStep').value);
  $$('.pack-step').forEach(el => el.classList.add('hidden'));
  $('#pack-step-'+step)?.classList.remove('hidden');

  $('#packName').value = state.pack.name;
  $('#packPaths').value = state.pack.paths.join(', ');
  $('#packOutput').value = state.pack.output;

  // presets
  const presets = (state.meta?.presets || []).map(x => ({
    key: x.key,
    label: x.key,
    desc: x.description,
    tags: (x.tags || []).slice(0, 4),
  }));
  const grid = $('#presetGrid');
  grid.innerHTML = '';
  for (const p of presets) {
    const btn = document.createElement('button');
    const active = (state.preset === p.key);
    btn.className = `text-left rounded-2xl border px-4 py-4 transition hover:-translate-y-0.5 hover:bg-slate-900/60 ${active ? 'border-emerald-600 bg-emerald-500/5' : 'border-slate-800 bg-slate-950/40'}`;
    btn.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="text-slate-100 font-medium">${p.label}</div>
          <div class="text-xs text-slate-400 mt-1">${clampStr(p.desc || '', 80)}</div>
        </div>
        <div class="text-[10px] text-slate-400 border border-slate-800 rounded-lg px-2 py-1">preset</div>
      </div>
      <div class="flex flex-wrap gap-1 mt-3">
        ${(p.tags||[]).map(t => `<span class="text-[10px] px-2 py-1 rounded-full border border-slate-800 text-slate-300 bg-slate-900/30">${t}</span>`).join('')}
      </div>
    `;
    btn.addEventListener('click', () => {
      state.preset = p.key;
      // Suggest defaults from preset
      const host = (state.meta?.host || '').toLowerCase() || 'host';
      state.pack.name = `${host}-${p.key}`.replace(/[^a-z0-9-]+/g,'-').replace(/-+/g,'-').replace(/^-|-$/g,'').slice(0,64) || 'bundle';
      const spec = (state.meta?.presets||[]).find(x => x.key === p.key);
      if (spec && Array.isArray(spec.paths) && !state.pack.paths.length) {
        state.pack.paths = spec.paths;
      }
      toastKey('toast.preset', { preset: p.key });
      renderPackWizard();
    });
    grid.appendChild(btn);
  }

  const sbox = $('#sensitiveList');
  sbox.innerHTML = '';
  const sensitivePaths = state.pack.scan?.sensitive || [];
  const sensitive = sensitivePaths.map(p => ({ path: p, reason: 'Sensitive path detected' }));
  state.pack.sensitive = sensitive;

  if (!state.pack.scan) {
    const msg = document.createElement('div');
    msg.className = 'text-xs text-slate-500';
    msg.textContent = 'Run the scan (Next) to list sensitive paths.';
    sbox.appendChild(msg);
  } else if (!sensitive.length) {
    const msg = document.createElement('div');
    msg.className = 'text-xs text-slate-400';
    msg.textContent = 'No sensitive paths detected in this scan.';
    sbox.appendChild(msg);
  }

  for (const item of sensitive) {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between gap-3 px-3 py-2 rounded-xl border border-slate-800 bg-slate-950/40';
    const allowed = !!state.pack.sensitiveAllow[item.path];
    row.innerHTML = `
      <div>
        <div class="text-sm text-slate-200 font-mono">${item.path}</div>
        <div class="text-xs text-slate-400">${item.reason}</div>
      </div>
      <label class="inline-flex items-center gap-2 cursor-pointer">
        <input type="checkbox" class="accent-emerald-500" ${allowed ? 'checked' : ''} />
        <span class="text-xs ${allowed ? 'text-emerald-200' : 'text-slate-300'}">${allowed ? 'include' : 'exclude'}</span>
      </label>
    `;
    row.querySelector('input').addEventListener('change', (e) => {
      state.pack.sensitiveAllow[item.path] = !!e.target.checked;
      if (state.pack.sensitiveAllow[item.path]) {
        toastKey('toast.includingSensitiveOne', { path: item.path }, 'warn');
      } else {
        toastKey('toast.excludingSensitiveOne', { path: item.path }, 'info');
      }
      renderPackWizard();
    });
    sbox.appendChild(row);
  }

  // job output
  $('#packJob').textContent = state.pack.job ? JSON.stringify(state.pack.job, null, 2) : '(no job)';
}

async function startPackJob() {
  const name = ($('#packName').value || '').trim();
  const paths = ($('#packPaths').value || '').split(',').map(s => s.trim()).filter(Boolean);
  const output = ($('#packOutput').value || '').trim();
  if (!name) return toastKey('toast.nameRequired', {}, 'error');
  state.pack.name = name;
  state.pack.paths = paths;
  state.pack.output = output;

  $('#packRunBtn').disabled = true;
  $('#packRunBtn').classList.add('opacity-60');
  $('#packRunStatus').textContent = t(state.lang, 'status.starting');

  try {
    // Convert sensitive toggles into excludes (default exclude sensitive paths).
    const excludes = [];
    for (const sp of (state.pack.scan?.sensitive || [])) {
      if (!state.pack.sensitiveAllow[sp]) {
        excludes.push(sp);
      }
    }

    const body = { name, paths, preset: state.preset, excludes };
    if (output) body.output = output;
    const r = await api('/api/pack', { method: 'POST', body: JSON.stringify(body) });
    state.pack.jobId = r.job_id;
    $('#packRunStatus').textContent = `job ${r.job_id}`;

    // SSE stream (fallback to polling if it fails)
    try {
      const es = new EventSource(`/api/jobs/${state.pack.jobId}/events`);
      await new Promise((resolve) => {
        es.onmessage = (ev) => {
          const j = JSON.parse(ev.data);
          state.pack.job = j;

          const p = j.result && j.result.progress;
          if (p && p.type === 'pack_progress') {
            const pct = p.bytes_total ? Math.min(100, Math.round((p.bytes_done / p.bytes_total) * 100)) : Math.min(100, Math.round((p.files_done / p.files_total) * 100));
            $('#packRunStatus').textContent = `packing ${pct}% · ${p.files_done}/${p.files_total}`;
          } else if (p && p.type === 'scan_progress') {
            $('#packRunStatus').textContent = `scanning · ${p.files || 0} files`;
          } else if (p && p.type === 'scan_done') {
            $('#packRunStatus').textContent = `scanned · ${p.files || 0} files`;
          } else if (p && p.type === 'pack_done') {
            $('#packRunStatus').textContent = t(state.lang, 'status.finalizing');
          }

          $('#packJob').textContent = JSON.stringify(j, null, 2);
          if (j.status === 'done') { toastKey('toast.packCompleted', {}, 'info'); es.close(); resolve(); }
          if (j.status === 'error') { toastKey('toast.packFailed', { err: (j.error||'') }, 'error'); es.close(); resolve(); }
        };
        es.onerror = () => {
          es.close();
          resolve();
        };
      });
    } catch {
      // ignore
    }

    if (!state.pack.job || (state.pack.job.status !== 'done' && state.pack.job.status !== 'error')) {
      while (true) {
        const j = await api(`/api/jobs/${state.pack.jobId}`);
        state.pack.job = j;
        $('#packJob').textContent = JSON.stringify(j, null, 2);
        if (j.status === 'done') { toast('Pack completed', 'info'); break; }
        if (j.status === 'error') { toast('Pack failed: ' + (j.error||''), 'error'); break; }
        await sleep(900);
      }
    }
  } catch (e) {
    toast(String(e), 'error');
    $('#packRunStatus').textContent = 'error';
  } finally {
    $('#packRunBtn').disabled = false;
    $('#packRunBtn').classList.remove('opacity-60');
  }
}

async function boot() {
  // meta
  try {
    state.meta = await api('/api/meta');
    state.lang = (state.meta.language || 'en').toLowerCase();
    // meta.version is raw `peridot --version` output (e.g. "peridot 0.4.7")
    $('#metaVersion').textContent = state.meta.version || 'unknown';

    // apply translations
    $$('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) el.textContent = t(state.lang, key);
    });
  } catch {
    // ok
  }

  // nav
  $$('.navbtn').forEach(b => b.addEventListener('click', () => setRoute(b.dataset.route)));

  // palette
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openPalette();
    }
    if (e.key === 'Escape') {
      closePalette();
    }
  });
  $('#paletteOverlay').addEventListener('click', closePalette);
  $('#paletteInput').addEventListener('input', renderPalette);

  // pack wizard buttons
  $('#packPrev').addEventListener('click', () => {
    const v = Math.max(1, Number($('#packStep').value) - 1);
    $('#packStep').value = String(v);
    renderPackWizard();
  });
  $('#packNext').addEventListener('click', async () => {
    const current = Number($('#packStep').value);
    const v = Math.min(4, current + 1);
    // persist fields
    state.pack.name = ($('#packName').value||'').trim();
    state.pack.paths = ($('#packPaths').value||'').split(',').map(s=>s.trim()).filter(Boolean);
    state.pack.output = ($('#packOutput').value||'').trim();

    // entering sensitive step: run scan
    if (v === 3) {
      try {
        toastKey('toast.scan');
        state.pack.scan = await api('/api/pack/scan', { method: 'POST', body: JSON.stringify({ preset: state.preset, paths: state.pack.paths }) });
        // initialize sensitive allow map (default exclude)
        state.pack.sensitiveAllow = {};
        for (const p of (state.pack.scan.sensitive || [])) state.pack.sensitiveAllow[p] = false;
      } catch (e) {
        toastKey('toast.scanFailed', { err: String(e) }, 'error');
      }
    }

    $('#packStep').value = String(v);
    renderPackWizard();
  });
  $('#packRunBtn').addEventListener('click', () => startPackJob());

  // sensitive bulk actions
  $('#sensExcludeAll')?.addEventListener('click', () => {
    for (const item of state.pack.sensitive) state.pack.sensitiveAllow[item.path] = false;
    toastKey('toast.excludedAllSensitive');
    renderPackWizard();
  });
  $('#sensIncludeAll')?.addEventListener('click', () => {
    for (const item of state.pack.sensitive) state.pack.sensitiveAllow[item.path] = true;
    toastKey('toast.includingAllSensitive', {}, 'warn');
    renderPackWizard();
  });

  render();
}

boot();
