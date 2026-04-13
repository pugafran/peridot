import { t } from './i18n.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function fmtBytes(n) {
  const v = Number(n || 0);
  if (!Number.isFinite(v)) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let x = v;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${x.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

async function setClipboard(text) {
  const v = String(text ?? '');
  if (!v) return false;

  // navigator.clipboard is async and may throw/reject depending on permissions.
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(v);
      return true;
    }
  } catch {
    // fall through to legacy path
  }

  // Legacy fallback (works in more contexts, including some local-file setups).
  try {
    const ta = document.createElement('textarea');
    ta.value = v;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return !!ok;
  } catch {
    return false;
  }
}

async function revealPath(path) {
  await api('/api/os/reveal', { method: 'POST', body: JSON.stringify({ path }) });
}

const state = {
  route: 'home',
  lang: 'en',
  preset: null,
  pack: {
    name: '',
    paths: [],
    output: '',
    userExcludes: [],
    sensitive: [],
    sensitiveAllow: {},
    scan: null,
    scanning: false,
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

  const ct = r.headers.get('content-type') || '';
  const isJson = ct.includes('application/json');

  if (!r.ok) {
    // FastAPI errors are usually JSON: {"detail": "..."}.
    // Prefer showing a clean message instead of a raw HTML/JSON blob.
    if (isJson) {
      let j = null;
      try { j = await r.json(); } catch { j = null; }
      if (j) {
        const msg = (j && (j.detail || j.error)) ? (j.detail || j.error) : JSON.stringify(j);
        throw new Error(String(msg));
      }
    }
    const txt = await r.text();
    throw new Error((txt || '').trim() || `HTTP ${r.status}`);
  }

  if (isJson) return await r.json();
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

function parsePathsInput(raw) {
  const text = (raw || '').trim();
  if (!text) return [];
  const hasNewline = /\r|\n/.test(text);
  const sep = hasNewline ? /\r?\n/ : (text.includes(';') ? ';' : ',');
  const parts = text.split(sep);
  return parts.map(s => s.trim()).filter(Boolean);
}

function parsePatternsInput(raw) {
  // For excludes we intentionally do NOT treat ';' as a separator by default,
  // because Windows PATH-like strings often contain semicolons.
  const text = (raw || '').trim();
  if (!text) return [];
  const hasNewline = /\r|\n/.test(text);
  const sep = hasNewline ? /\r?\n/ : (text.includes(',') ? ',' : /\s+/);
  const parts = text.split(sep);
  return parts.map(s => s.trim()).filter(Boolean);
}

function renderPackWizard() {
  // step visibility
  const step = Number($('#packStep').value);
  $$('.pack-step').forEach(el => el.classList.add('hidden'));
  $('#pack-step-'+step)?.classList.remove('hidden');

  $('#packName').value = state.pack.name;
  $('#packPaths').value = state.pack.paths.join('\n');
  $('#packOutput').value = state.pack.output;
  $('#packExcludes').value = (state.pack.userExcludes || []).join('\n');

  // presets
  const runtime = state.meta?.runtime || {};
  const isWindows = String(runtime.os_name || '').toLowerCase() === 'nt' || String(runtime.sys_platform || '').toLowerCase().startsWith('win');

  const presets = (state.meta?.presets || []).map(x => ({
    key: x.key,
    label: x.key,
    desc: x.description,
    platform: x.platform,
    shell: x.shell,
    tags: (x.tags || []).slice(0, 4),
  })).sort((a, b) => {
    // Windows-first: show Windows presets first when running on Windows.
    const score = (p) => {
      const plat = String(p.platform || '').toLowerCase();
      if (isWindows && plat === 'windows') return 2;
      if (isWindows && plat && plat !== 'windows') return 0;
      return 1;
    };
    const sa = score(a), sb = score(b);
    if (sa !== sb) return sb - sa;
    return String(a.key).localeCompare(String(b.key));
  });
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

  const ssum = $('#scanSummary');
  const sbox = $('#sensitiveList');
  ssum.textContent = '';
  sbox.innerHTML = '';

  const sensitivePaths = state.pack.scan?.sensitive || [];
  const sensitive = sensitivePaths.map(p => ({ path: p, reason: 'Sensitive path detected' }));
  state.pack.sensitive = sensitive;

  if (!state.pack.scan) {
    if (state.pack.scanning) {
      ssum.textContent = 'Scanning…';
      const msg = document.createElement('div');
      msg.className = 'text-xs text-slate-500';
      msg.textContent = 'This may take a moment on large presets.';
      sbox.appendChild(msg);
    } else {
      ssum.textContent = 'Not scanned yet.';
      const msg = document.createElement('div');
      msg.className = 'text-xs text-slate-500';
      msg.textContent = 'Run the scan (Next) to list sensitive paths.';
      sbox.appendChild(msg);
    }
  } else {
    const files = state.pack.scan.files ?? 0;
    const bytes = state.pack.scan.bytes ?? 0;
    const fmtBytes = (n) => {
      if (!n) return '0 B';
      const u = ['B','KB','MB','GB','TB'];
      let i = 0;
      let v = n;
      while (v >= 1024 && i < u.length-1) { v /= 1024; i++; }
      const s = (i === 0) ? String(Math.round(v)) : v.toFixed(v >= 10 ? 1 : 2);
      return `${s} ${u[i]}`;
    };
    const missingPaths = (state.pack.scan.missing_paths || []);
    const skippedPaths = (state.pack.scan.skipped_paths || []);
    const missing = missingPaths.length;
    const skipped = skippedPaths.length;
    ssum.textContent = `Scan: ${files} files · ${fmtBytes(bytes)} · ${sensitive.length} sensitive`
      + (missing ? ` · ${missing} missing` : '')
      + (skipped ? ` · ${skipped} skipped` : '');

    if (missing || skipped) {
      const wrap = document.createElement('div');
      wrap.className = 'mt-3 rounded-xl border border-slate-800 bg-slate-950/30 p-3';
      wrap.innerHTML = `
        <div class="text-xs text-slate-300 font-medium">Paths not scanned</div>
        <div class="text-[11px] text-slate-500 mt-1">Missing paths are not present on this machine. Skipped paths are typically symlinks (safe to ignore).</div>
        <div class="mt-2 flex flex-col gap-1"></div>
      `;
      const list = wrap.querySelector('div.mt-2');
      const add = (label, items) => {
        if (!items.length) return;
        const h = document.createElement('div');
        h.className = 'text-[11px] text-slate-500 mt-2';
        h.textContent = label;
        list.appendChild(h);
        for (const mp of items.slice(0, 18)) {
          const ln = document.createElement('div');
          ln.className = 'text-xs text-slate-300 font-mono truncate';
          ln.textContent = mp;
          list.appendChild(ln);
        }
        if (items.length > 18) {
          const ln = document.createElement('div');
          ln.className = 'text-xs text-slate-500';
          ln.textContent = `…and ${items.length - 18} more`;
          list.appendChild(ln);
        }
      };
      add('Missing', missingPaths);
      add('Skipped', skippedPaths);
      sbox.appendChild(wrap);
    }

    if (!sensitive.length) {
      const msg = document.createElement('div');
      msg.className = 'text-xs text-slate-400 mt-3';
      msg.textContent = 'No sensitive paths detected in this scan.';
      sbox.appendChild(msg);
    }
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
  const paths = parsePathsInput($('#packPaths').value || '');
  const output = ($('#packOutput').value || '').trim();
  const userExcludes = parsePatternsInput($('#packExcludes').value || '');
  if (!name) return toastKey('toast.nameRequired', {}, 'error');
  state.pack.name = name;
  state.pack.paths = paths;
  state.pack.output = output;
  state.pack.userExcludes = userExcludes;

  $('#packRunBtn').disabled = true;
  $('#packRunBtn').classList.add('opacity-60');
  $('#packRunStatus').textContent = t(state.lang, 'status.starting');

  try {
    // Convert sensitive toggles into excludes (default exclude sensitive paths),
    // and merge with user-supplied exclude patterns.
    const excludes = [];
    for (const pat of (state.pack.userExcludes || [])) excludes.push(pat);
    for (const sp of (state.pack.scan?.sensitive || [])) {
      if (!state.pack.sensitiveAllow[sp]) excludes.push(sp);
    }
    const uniq = Array.from(new Set(excludes));

    const body = { name, paths, preset: state.preset, excludes: uniq };
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

          const outputPath = j.result && j.result.output;
          if (outputPath) {
            $('#btnPackReveal').disabled = false;
            $('#btnPackCopy').disabled = false;
            $('#btnPackReveal').onclick = async () => {
              try { await revealPath(outputPath); } catch (e) { toast(String(e), 'error'); }
            };
            $('#btnPackCopy').onclick = async () => { if (await setClipboard(outputPath)) toastKey('toast.copied'); };
          }

          const p = j.result && j.result.progress;
          if (p && p.type === 'pack_progress') {
            const pct = p.bytes_total ? Math.min(100, Math.round((p.bytes_done / p.bytes_total) * 100)) : Math.min(100, Math.round((p.files_done / p.files_total) * 100));
            $('#packProgressBar').style.width = `${pct}%`;
            const cur = p.path ? ` · ${clampStr(String(p.path).replace(/\\/g,'/'), 54)}` : '';
            const sk = (typeof p.skipped === 'number' && p.skipped > 0) ? ` · skipped ${p.skipped}` : '';
            $('#packRunStatus').textContent = `packing ${pct}% · ${p.files_done}/${p.files_total}${sk}${cur}`;
          } else if (p && p.type === 'pack_skip') {
            // Surface skips in the status line (common on Windows when some files are locked).
            const cur = p.path ? ` · ${clampStr(String(p.path).replace(/\\/g,'/'), 54)}` : '';
            const sk = (typeof p.skipped === 'number' && p.skipped > 0) ? `skipped ${p.skipped}` : 'skipped file';
            $('#packRunStatus').textContent = `${sk}${cur}`;
          } else if (p && p.type === 'scan_start') {
            $('#packProgressBar').style.width = '5%';
            $('#packRunStatus').textContent = 'scanning…';
          } else if (p && p.type === 'scan_progress') {
            $('#packProgressBar').style.width = '10%';
            const cur = p.current ? ` · ${clampStr(String(p.current).replace(/\\/g,'/'), 54)}` : '';
            $('#packRunStatus').textContent = `scanning · ${p.files || 0} files${cur}`;
          } else if (p && p.type === 'scan_done') {
            $('#packProgressBar').style.width = '20%';
            $('#packRunStatus').textContent = `scanned · ${p.files || 0} files`;
          } else if (p && p.type === 'pack_done') {
            $('#packProgressBar').style.width = '95%';
            $('#packRunStatus').textContent = t(state.lang, 'status.finalizing');
          }

          if (j.status === 'done' && j.result && j.result.output) {
            const out = j.result.output;
            const bytes = j.result.output_bytes ? fmtBytes(j.result.output_bytes) : '';
            $('#packSummary').textContent = `output: ${out}${bytes ? ' · ' + bytes : ''}`;
            $('#packProgressBar').style.width = '100%';
          }
          if (j.status === 'error') {
            $('#packSummary').textContent = `error: ${j.error || ''}`;
            $('#packProgressBar').style.width = '100%';
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
        if (j.status === 'done') {
          if (j.result && j.result.output) {
            const out = j.result.output;
            const bytes = j.result.output_bytes ? fmtBytes(j.result.output_bytes) : '';
            $('#packSummary').textContent = `output: ${out}${bytes ? ' · ' + bytes : ''}`;
            $('#packProgressBar').style.width = '100%';
          }
          toastKey('toast.packCompleted', {}, 'info');
          break;
        }
        if (j.status === 'error') {
          $('#packSummary').textContent = `error: ${j.error || ''}`;
          $('#packProgressBar').style.width = '100%';
          toastKey('toast.packFailed', { err: (j.error||'') }, 'error');
          break;
        }
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
    if (!state.meta.version && state.meta.version_error) {
      toast(`Peridot CLI not detected (${state.meta.version_error}). Using: ${JSON.stringify(state.meta.peridot_cmd || [])}`, 'warn');
    }
    const gh = state.meta.gui && state.meta.gui.host ? state.meta.gui.host : '127.0.0.1';
    const gp = state.meta.gui && state.meta.gui.port ? state.meta.gui.port : 8844;
    const addr = `${gh}:${gp}`;
    const metaAddr = $('#metaAddr');
    if (metaAddr) metaAddr.textContent = addr;

    // Ensure we always have a preset selected so Pack never triggers
    // interactive CLI prompts (which will crash in GUI subprocess mode).
    // Windows-first: pick a Windows preset when running on Windows.
    if (!state.preset) {
      const runtime = state.meta?.runtime || {};
      const isWindows = String(runtime.os_name || '').toLowerCase() === 'nt' || String(runtime.sys_platform || '').toLowerCase().startsWith('win');
      const presets = Array.isArray(state.meta.presets) ? state.meta.presets : [];

      const score = (p) => {
        const plat = String(p.platform || '').toLowerCase();
        if (isWindows && plat === 'windows') return 2;
        if (isWindows && plat && plat !== 'windows') return 0;
        return 1;
      };

      const best = presets
        .slice()
        .sort((a, b) => {
          const sa = score(a), sb = score(b);
          if (sa !== sb) return sb - sa;
          return String(a.key || '').localeCompare(String(b.key || ''));
        })[0];

      if (best && best.key) state.preset = best.key;
    }

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
  $('#paletteInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const first = $('#paletteItems button');
      if (first) {
        e.preventDefault();
        first.click();
      }
    }
  });

  // inspect
  async function refreshBundles() {
    try {
      const data = await api('/api/bundles');
      const sel = $('#bundleSelect');
      sel.innerHTML = '';
      const makeOpt = (item) => {
        const opt = document.createElement('option');
        opt.value = item.path;
        opt.textContent = `${item.name} · ${item.source}`;
        return opt;
      };
      for (const it of data.items || []) sel.appendChild(makeOpt(it));
      for (const it of (data.history || []).slice(0, 200)) sel.appendChild(makeOpt(it));
    } catch (e) {
      toastKey('toast.inspectFailed', { err: String(e) }, 'error');
    }
  }

  $('#btnRefreshBundles')?.addEventListener('click', refreshBundles);
  $('#bundleSelect')?.addEventListener('change', (e) => {
    const v = e.target.value;
    if (v) $('#inspectPath').value = v;
  });
  // clipboard + reveal helpers are defined at module scope

  function safeGet(obj, path, fallback = null) {
    try {
      return path.split('.').reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : undefined), obj) ?? fallback;
    } catch {
      return fallback;
    }
  }

  // fmtBytes() helper is defined at module scope

  $('#btnInspect')?.addEventListener('click', async () => {
    $('#inspectStatus').textContent = 'loading…';
    try {
      const p = ($('#inspectPath').value || '').trim();
      const out = await api('/api/inspect?path=' + encodeURIComponent(p));
      $('#inspectOut').textContent = JSON.stringify(out, null, 2);

      const name = safeGet(out, 'bundle.name', '(unknown)');
      const created = safeGet(out, 'bundle.created_at', '');
      const files = Array.isArray(out.files) ? out.files.length : 0;
      const totalBytes = Array.isArray(out.files) ? out.files.reduce((acc, e) => acc + Number(e.size || 0), 0) : 0;
      const compat = safeGet(out, 'platform.os', '') ? `${safeGet(out, 'platform.os', '')}/${safeGet(out, 'platform.shell', '')}` : '';

      $('#inspectSummary').textContent = `${name} · ${files} files · ${fmtBytes(totalBytes)}${created ? ' · ' + created : ''}${compat ? ' · ' + compat : ''}`;

      $('#inspectStatus').textContent = 'ok';
      $('#btnInspectReveal').disabled = !p;
      $('#btnInspectCopy').disabled = !p;
    } catch (e) {
      $('#inspectStatus').textContent = 'error';
      toastKey('toast.inspectFailed', { err: String(e) }, 'error');
    }
  });

  $('#btnInspectReveal')?.addEventListener('click', async () => {
    const p = ($('#inspectPath').value || '').trim();
    if (!p) return;
    try { await revealPath(p); } catch (e) { toastKey('toast.inspectFailed', { err: String(e) }, 'error'); }
  });

  $('#btnInspectCopy')?.addEventListener('click', async () => {
    const p = ($('#inspectPath').value || '').trim();
    if (!p) return;
    if (await setClipboard(p)) toastKey('toast.copied');
  });

  // apply
  let lastPlan = null;

  function updateApplyEnabled() {
    const token = String(lastPlan && lastPlan.apply_token ? lastPlan.apply_token : '');
    const confirm = String($('#applyTokenConfirm')?.value || '');
    $('#btnApplyRun').disabled = !(token && confirm && token === confirm);
  }

  $('#applyTokenConfirm')?.addEventListener('input', updateApplyEnabled);

  $('#btnApplyPlan')?.addEventListener('click', async () => {
    $('#applyStatus').textContent = 'planning…';
    $('#applyProgressBar').style.width = '0%';
    try {
      const packagePath = ($('#applyPath').value || '').trim();
      const target = ($('#applyTarget').value || '').trim();
      lastPlan = await api('/api/apply/plan', {
        method: 'POST',
        body: JSON.stringify({ package: packagePath, target })
      });
      $('#applyOut').textContent = JSON.stringify(lastPlan, null, 2);

      const plan = Array.isArray(lastPlan.plan) ? lastPlan.plan : [];
      const creates = plan.filter(p => p.action === 'create').length;
      const overwrites = plan.filter(p => p.action === 'overwrite').length;
      const bytes = plan.reduce((acc, p) => acc + Number(p.size || 0), 0);
      const compat = lastPlan.compatible === false ? `WARNING: ${lastPlan.compatibility_message || 'platform mismatch'}` : 'compatible';
      $('#applySummary').textContent = `${compat} · ${plan.length} changes (${creates} create, ${overwrites} overwrite) · ${fmtBytes(bytes)}`;

      $('#applyStatus').textContent = 'planned';

      // Show apply token and require manual confirmation (safety).
      $('#applyToken').value = String(lastPlan.apply_token || '');
      $('#applyTokenConfirm').value = '';
      updateApplyEnabled();
      $('#applyProgressBar').style.width = '15%';
    } catch (e) {
      $('#applyStatus').textContent = 'error';
      toastKey('toast.applyPlanFailed', { err: String(e) }, 'error');
    }
  });

  $('#btnApplyRun')?.addEventListener('click', async () => {
    const token = String($('#applyTokenConfirm')?.value || '');
    if (!lastPlan || !lastPlan.apply_token || !token) {
      toastKey('toast.applyRunFailed', { err: 'missing token' }, 'error');
      return;
    }
    if (token !== String(lastPlan.apply_token)) {
      toastKey('toast.applyRunFailed', { err: 'token mismatch' }, 'error');
      return;
    }
    $('#applyStatus').textContent = 'applying…';
    try {
      const packagePath = ($('#applyPath').value || '').trim();
      const target = ($('#applyTarget').value || '').trim();
      const r = await api('/api/apply/run', {
        method: 'POST',
        body: JSON.stringify({ package: packagePath, target, apply_token: token })
      });
      const es = new EventSource(`/api/jobs/${r.job_id}/events`);
      es.onmessage = (ev) => {
        const j = JSON.parse(ev.data);
        $('#applyOut').textContent = JSON.stringify(j, null, 2);

        const prog = j.result && j.result.progress ? j.result.progress : null;
        const pct = (prog && typeof prog.percent === 'number') ? prog.percent : null;
        if (pct !== null) {
          $('#applyProgressBar').style.width = `${Math.max(0, Math.min(100, pct))}%`;
          const cur = prog.current ? ` · ${clampStr(String(prog.current).replace(/\\/g,'/'), 54)}` : '';
          $('#applySummary').textContent = `${pct}%${cur}`;
        } else {
          // best-effort: show activity
          if (j.status === 'running') $('#applyProgressBar').style.width = '50%';
        }

        if (j.status === 'done') {
          $('#applySummary').textContent = 'done';
          $('#applyProgressBar').style.width = '100%';
        } else if (j.status === 'error') {
          $('#applySummary').textContent = `error: ${j.error || ''}`;
          $('#applyProgressBar').style.width = '100%';
        }

        if (j.status === 'done' || j.status === 'error') {
          $('#applyStatus').textContent = j.status;
          es.close();
        }
      };
      es.onerror = () => {
        es.close();
      };
    } catch (e) {
      $('#applyStatus').textContent = 'error';
      toastKey('toast.applyRunFailed', { err: String(e) }, 'error');
    }
  });

  // pack wizard buttons
  $('#btnUsePresetPaths')?.addEventListener('click', () => {
    if (!state.preset) {
      toast('Pick a preset first.', 'warn');
      return;
    }
    const spec = (state.meta?.presets || []).find(x => x.key === state.preset);
    const paths = (spec && Array.isArray(spec.paths)) ? spec.paths : [];
    if (!paths.length) {
      toast('This preset has no default paths.', 'warn');
      return;
    }
    state.pack.paths = paths;
    $('#packPaths').value = paths.join('\n');
    toastKey('toast.preset', { preset: state.preset });
  });

  $('#packPrev').addEventListener('click', () => {
    if (state.pack.scanning) return;
    const v = Math.max(1, Number($('#packStep').value) - 1);
    $('#packStep').value = String(v);
    renderPackWizard();
  });
  $('#packNext').addEventListener('click', async () => {
    if (state.pack.scanning) return;

    const current = Number($('#packStep').value);
    const next = Math.min(4, current + 1);
    // persist fields
    state.pack.name = ($('#packName').value||'').trim();
    state.pack.paths = parsePathsInput($('#packPaths').value||'');
    state.pack.output = ($('#packOutput').value||'').trim();
    state.pack.userExcludes = parsePatternsInput($('#packExcludes').value||'');

    // entering sensitive step: run scan
    if (next === 3) {
      try {
        toastKey('toast.scan');
        state.pack.scanning = true;
        // Show step 3 immediately so the user sees "Scanning…" rather than
        // a frozen step 2.
        $('#packStep').value = String(next);
        renderPackWizard();

        state.pack.scan = await api('/api/pack/scan', {
          method: 'POST',
          body: JSON.stringify({ preset: state.preset, paths: state.pack.paths, excludes: (state.pack.userExcludes || []) })
        });
        // initialize sensitive allow map (default exclude)
        state.pack.sensitiveAllow = {};
        for (const p of (state.pack.scan.sensitive || [])) state.pack.sensitiveAllow[p] = false;
      } catch (e) {
        // If scanning fails, keep the user on the current step so they can fix inputs.
        $('#packStep').value = String(current);
        toastKey('toast.scanFailed', { err: String(e) }, 'error');
        return;
      } finally {
        state.pack.scanning = false;
      }
    }

    $('#packStep').value = String(next);
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

  // expose refresh hooks for buttons
  window.__refreshDoctor = () => renderDoctor();
  window.__refreshSettings = () => renderSettings();

  render();
}

boot();
