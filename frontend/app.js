import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const state = {
  jobs: [],
  activeId: null,
  detailTimer: null,
  detailViewer: null,
  compareViewers: null,
};

// ---------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const dropzone = $('#dropzone');
const fileInput = $('#fileInput');
const demoBtn = $('#demoBtn');
const demoStructBtn = $('#demoStructBtn');
const jobsEl = $('#jobs');
const jobCount = $('#jobCount');
const detailEl = $('#detail');
const viewerEl = $('#viewer');

const STAGE_NAMES = {
  uploaded: 'Uploaded',
  validated: 'Validated',
  parsed: 'Parsed',
  geometry: 'Geometry',
  optimized: 'Optimised',
  metadata: 'Metadata',
};

const STATUS_LABEL = {
  queued: 'Queued',
  processing: 'Processing',
  completed: 'Ready',
  failed: 'Failed',
};

function fmtBytes(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function fmtNum(n) {
  return n == null ? '' : Number(n).toLocaleString();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText} ${body}`.trim());
  }
  return res.json();
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const job = await api('/api/jobs', { method: 'POST', body: fd });
  state.activeId = job.id;
  refreshJobs();
  openDetail(job.id);
}

// ---------------------------------------------------------------------------
// Upload UX
// ---------------------------------------------------------------------------
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  fileInput.value = '';
});
['dragenter', 'dragover'].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add('drag'); }));
['dragleave', 'drop'].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove('drag'); }));
dropzone.addEventListener('drop', (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) uploadFile(f);
});

function bindDemoButton(btn, sample) {
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = 'Starting…';
    try {
      const job = await api(`/api/demo/${sample}`, { method: 'POST' });
      state.activeId = job.id;
      refreshJobs();
      openDetail(job.id);
    } catch (err) {
      alert('Demo failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });
}
bindDemoButton(demoBtn, 'architecture');
bindDemoButton(demoStructBtn, 'structural');

// ---------------------------------------------------------------------------
// Jobs list
// ---------------------------------------------------------------------------
async function refreshJobs() {
  try {
    state.jobs = await api('/api/jobs');
  } catch (err) {
    return;
  }
  renderJobs();
  populateCompareSelects();
  if (state.activeId) {
    const j = state.jobs.find((x) => x.id === state.activeId);
    if (j) renderDetail(j);
  }
}

function renderJobs() {
  jobCount.textContent = state.jobs.length
    ? `${state.jobs.length} job${state.jobs.length > 1 ? 's' : ''}`
    : '';
  if (!state.jobs.length) {
    jobsEl.innerHTML = '<div class="empty">No jobs yet. Upload a file or run a sample.</div>';
    return;
  }
  jobsEl.innerHTML = '';
  for (const j of state.jobs) {
    const el = document.createElement('div');
    el.className = 'job';
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    const icon = j.format === 'rvt' ? '🏗' : j.format === 'ifc' ? '🏠' : '🧊';
    const sub = `${j.format.toUpperCase()} · ${fmtBytes(j.sizeBytes)} · ${new Date(j.createdAt * 1000).toLocaleTimeString()}`;
    el.innerHTML = `
      <span class="job-icon">${icon}</span>
      <span>
        <div class="job-name">${esc(j.filename)}</div>
        <div class="job-sub">${sub}</div>
      </span>
      <span class="job-status st-${j.status}">${STATUS_LABEL[j.status] || j.status}</span>
      <span class="job-arrow">›</span>
    `;
    el.addEventListener('click', () => openDetail(j.id));
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(j.id); });
    jobsEl.appendChild(el);
  }
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------
function openDetail(id) {
  state.activeId = id;
  detailEl.classList.remove('hidden');
  $('#closeDetail').onclick = () => { detailEl.classList.add('hidden'); state.activeId = null; };
  const j = state.jobs.find((x) => x.id === id);
  if (j) renderDetail(j);
  startDetailPolling();
}

function startDetailPolling() {
  if (state.detailTimer) clearInterval(state.detailTimer);
  state.detailTimer = setInterval(async () => {
    if (!state.activeId) { clearInterval(state.detailTimer); return; }
    try {
      const j = await api(`/api/jobs/${state.activeId}`);
      const idx = state.jobs.findIndex((x) => x.id === j.id);
      if (idx >= 0) state.jobs[idx] = j; else state.jobs.push(j);
      renderJobs();
      renderDetail(j);
      if (j.status === 'completed' || j.status === 'failed') {
        clearInterval(state.detailTimer);
        state.detailTimer = null;
      }
    } catch (err) { /* ignore transient */ }
  }, 700);
}

function detailViewer() {
  if (!state.detailViewer) state.detailViewer = createViewer(viewerEl);
  return state.detailViewer;
}

function renderDetail(j) {
  $('#detailName').textContent = j.filename;
  const badges = [];
  badges.push(`<span class="badge">${j.format.toUpperCase()}</span>`);
  badges.push(`<span class="badge">${fmtBytes(j.sizeBytes)}</span>`);
  if (j.summary) {
    badges.push(`<span class="badge">${fmtNum(j.summary.totalElements)} elements</span>`);
    badges.push(`<span class="badge">${fmtNum(j.summary.totalTriangles)} triangles</span>`);
  }
  $('#detailBadges').innerHTML = badges.join('');

  renderStages(j);
  renderLogs(j);
  renderDownloads(j);
  renderApi(j);

  const v = detailViewer();
  if (j.outputs && j.outputs.modelGlb && j.status === 'completed') {
    v.load(j.outputs.modelGlb);
  } else if (j.status === 'failed') {
    v.showPlaceholder('Processing failed — see logs');
  } else {
    v.showPlaceholder('Waiting for GLB derivative…');
  }
}

function renderStages(j) {
  const el = $('#stages');
  const names = Object.keys(STAGE_NAMES);
  const byName = {};
  (j.stages || []).forEach((s) => { byName[s.name] = s; });
  el.innerHTML = names.map((n) => {
    const s = byName[n];
    const status = s ? s.status : 'pending';
    return `<div class="stage">
      <span class="stage-dot ${status}"></span>
      <span class="stage-name">${STAGE_NAMES[n]}</span>
      <span class="stage-msg">${s ? esc(s.message || '') : ''}</span>
    </div>`;
  }).join('');
}

function renderLogs(j) {
  $('#logs').textContent = (j.logs || []).join('\n') || 'No logs yet.';
}

function renderDownloads(j) {
  const el = $('#downloads');
  const out = j.outputs || {};
  const items = [
    { href: out.modelGlb, label: '⬇ model.glb', hint: 'GLB binary (self-contained)' },
    { href: out.modelGltf, label: '⬇ model.gltf', hint: 'GLTF + .bin' },
    { href: out.metadata, label: '⬇ metadata.json', hint: 'Structured BIM metadata' },
  ];
  const ready = j.status === 'completed';
  let html = items.map((it) => `
    <a class="dl-btn ${ready && it.href ? '' : 'disabled'}" ${ready && it.href ? `href="${it.href}" download` : ''} title="${it.hint}">
      ${it.label}
    </a>`).join('');

  if (out.cloud && ready) {
    html += Object.entries(out.cloud).map(([name, url]) => `
      <a class="dl-btn" href="${esc(url)}" target="_blank" rel="noopener" title="Cloud (S3) presigned link">
        ☁ ${esc(name)}
      </a>`).join('');
  }
  el.innerHTML = html;
}

function renderApi(j) {
  const host = location.origin;
  const snippet = `# Upload
curl -X POST ${host}/api/jobs -F "file=@model.ifc"

# Track
curl ${host}/api/jobs/${j.id}

# Download derivatives
curl -o model.glb ${host}/api/jobs/${j.id}/download/model.glb
curl -o model.gltf ${host}/api/jobs/${j.id}/download/model.gltf
curl -o metadata.json ${host}/api/jobs/${j.id}/download/metadata.json`;
  $('#apiSnippet').textContent = snippet;
}

// Tabs
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    const name = t.dataset.tab;
    $(`#tab-${name}`).classList.add('active');
    if (name === 'metadata' && state.activeId) loadMetadata(state.activeId);
  });
});

async function loadMetadata(id) {
  const el = $('#metadata');
  try {
    const res = await fetch(`/api/jobs/${id}/download/metadata.json`);
    if (!res.ok) throw new Error(res.status);
    const meta = await res.json();
    const summary = meta.stats ? `Stats: ${JSON.stringify(meta.stats)}` : '';
    el.textContent = summary + '\n\n' + JSON.stringify(meta, null, 2);
  } catch (err) {
    el.textContent = 'Metadata not available yet.';
  }
}

// ---------------------------------------------------------------------------
// Three.js viewer factory
// ---------------------------------------------------------------------------
function createViewer(container) {
  const placeholder = container.querySelector('.viewer-placeholder');
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = null;

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);

  const hemi = new THREE.HemisphereLight(0xdfe8ff, 0x1a2230, 1.1);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(6, 10, 6);
  key.castShadow = true;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9db4d6, 0.7);
  fill.position.set(-5, 4, -4);
  scene.add(fill);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  const group = new THREE.Group();
  scene.add(group);

  let loadedUrl = null;

  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  resize();

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  function clear() {
    while (group.children.length) {
      const c = group.children.pop();
      if (c.geometry) c.geometry.dispose();
      if (c.material) {
        (Array.isArray(c.material) ? c.material : [c.material]).forEach((m) => m.dispose());
      }
    }
  }

  function fitCamera(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const dist = maxDim * 1.9;
    const dir = new THREE.Vector3(1, 0.8, 1).normalize();
    camera.position.copy(center).add(dir.multiplyScalar(dist));
    camera.near = maxDim / 100;
    camera.far = maxDim * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
  }

  function showPlaceholder(msg) {
    if (placeholder) {
      placeholder.textContent = msg;
      placeholder.style.display = 'grid';
    }
  }

  async function load(url) {
    if (loadedUrl === url) return;
    loadedUrl = url;
    if (placeholder) placeholder.style.display = 'none';
    try {
      const loader = new GLTFLoader();
      const gltf = await loader.loadAsync(url);
      clear();
      gltf.scene.traverse((o) => {
        if (o.isMesh) {
          o.castShadow = true;
          o.receiveShadow = true;
          if (o.geometry && o.geometry.getAttribute('color')) {
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            mats.forEach((m) => { m.vertexColors = true; m.needsUpdate = true; });
          }
        }
      });
      group.add(gltf.scene);
      fitCamera(gltf.scene);
      resize();
    } catch (err) {
      showPlaceholder('Could not load model: ' + err.message);
    }
  }

  return { load, clear, showPlaceholder, fitCamera, resize };
}

// ---------------------------------------------------------------------------
// Compare
// ---------------------------------------------------------------------------
function populateCompareSelects() {
  const completed = state.jobs.filter((j) => j.status === 'completed');
  const selA = $('#compareA');
  const selB = $('#compareB');
  const prevA = selA.value;
  const prevB = selB.value;
  const options = completed.map((j) =>
    `<option value="${j.id}">${esc(j.filename)}</option>`).join('') ||
    '<option value="">No completed jobs</option>';
  selA.innerHTML = options;
  selB.innerHTML = options;
  if (prevA && completed.some((j) => j.id === prevA)) selA.value = prevA;
  if (prevB && completed.some((j) => j.id === prevB)) selB.value = prevB;
  else if (completed.length >= 2) selB.value = completed[1].id;
  if (completed.length >= 1 && !selA.value) selA.value = completed[0].id;
}

function compareViewers() {
  if (!state.compareViewers) {
    state.compareViewers = {
      a: createViewer($('#viewerA')),
      b: createViewer($('#viewerB')),
    };
  }
  return state.compareViewers;
}

$('#compareBtn').addEventListener('click', async () => {
  const a = $('#compareA').value;
  const b = $('#compareB').value;
  if (!a || !b) { alert('Select two completed jobs to compare.'); return; }
  if (a === b) { alert('Pick two different jobs.'); return; }
  $('#compareResult').classList.remove('hidden');
  $('#diffStats').textContent = 'Loading…';
  $('#diffTables').innerHTML = '';

  try {
    const diff = await api(`/api/compare/${a}/${b}`);

    $('#compareLabelA').textContent = `${diff.a.filename} — ${fmtNum(diff.a.stats?.totalTriangles)} tris`;
    $('#compareLabelB').textContent = `${diff.b.filename} — ${fmtNum(diff.b.stats?.totalTriangles)} tris`;

    const ja = state.jobs.find((j) => j.id === a);
    const jb = state.jobs.find((j) => j.id === b);
    const v = compareViewers();
    if (ja?.outputs?.modelGlb) v.a.load(ja.outputs.modelGlb);
    if (jb?.outputs?.modelGlb) v.b.load(jb.outputs.modelGlb);

    renderDiffStats(diff);
    renderDiffTables(diff);
  } catch (err) {
    $('#diffStats').textContent = 'Compare failed: ' + err.message;
  }
});

function renderDiffStats(diff) {
  const { a, b } = diff;
  const sa = a.stats || {};
  const sb = b.stats || {};
  const card = (label, val, extra) => `
    <div class="diff-stat-card">
      <div class="title">${esc(label)}</div>
      <div class="big">${val}</div>
      <div class="rows">${extra}</div>
    </div>`;
  const catsA = Object.entries(sa.byCategory || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '—';
  const catsB = Object.entries(sb.byCategory || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '—';
  $('#diffStats').innerHTML =
    card('Elements — A', fmtNum(sa.totalElements), `<span>${esc(a.filename)}</span>`) +
    card('Elements — B', fmtNum(sb.totalElements), `<span>${esc(b.filename)}</span>`) +
    card('Triangles — A', fmtNum(sa.totalTriangles), `<span>${esc(catsA)}</span>`) +
    card('Triangles — B', fmtNum(sb.totalTriangles), `<span>${esc(catsB)}</span>`);
}

function renderDiffTables(diff) {
  const el = $('#diffTables');
  const ed = diff.elementDiff || {};
  const catRows = (diff.categoryDiff || []).map((c) =>
    `<tr><td>${esc(c.category)}</td><td>${c.a}</td><td>${c.b}</td>
     <td>${c.delta === 0 ? '—' : (c.delta > 0 ? '+' + c.delta : c.delta)}</td></tr>`).join('');

  const elRow = (e, cls, tag) => `
    <tr><td><span class="tag-${cls}">${tag}</span></td>
      <td>${esc(e.name || '—')}</td><td>${esc(e.category || '—')}</td>
      <td>${esc(e.material || '—')}</td></tr>`;

  const added = (ed.added || []).map((e) => elRow(e, 'add', '+')).join('');
  const removed = (ed.removed || []).map((e) => elRow(e, 'del', '−')).join('');
  const changed = (ed.changed || []).map((c) => `
    <tr><td><span class="tag-chg">~</span></td>
      <td>${esc(c.name || '—')}</td>
      <td>${esc(c.category || '—')}</td>
      <td><span class="tag-del">${esc(c.before?.material || '—')}</span>
          → <span class="tag-add">${esc(c.after?.material || '—')}</span></td></tr>`).join('');

  el.innerHTML = `
    <div class="diff-heading">Element diff — ${ed.common} common · ${(ed.added || []).length} added · ${(ed.removed || []).length} removed · ${(ed.changed || []).length} changed</div>
    <table class="diff-table">
      <thead><tr><th>Category</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
      <tbody>${catRows}</tbody>
    </table>
    ${(added || removed || changed) ? `
      <table class="diff-table">
        <thead><tr><th></th><th>Name</th><th>Category</th><th>Material</th></tr></thead>
        <tbody>${added}${removed}${changed}</tbody>
      </table>` : ''}`;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function refreshIntegrations() {
  try {
    const h = await api('/api/health');
    const it = h.integrations || {};
    const chip = (label, on) =>
      `<span class="iteg ${on ? 'on' : 'off'}"><span class="dot"></span>${label}</span>`;
    $('#integrations').innerHTML =
      chip('APS', !!it.aps) + chip('S3', !!it.s3);
  } catch (err) {
    $('#integrations').innerHTML = '<span class="iteg off"><span class="dot"></span>offline</span>';
  }
}

async function boot() {
  refreshIntegrations();
  await refreshJobs();
  if (!state.activeId && state.jobs.length) {
    const done = state.jobs.find((j) => j.status === 'completed') || state.jobs[0];
    openDetail(done.id);
  }
}
state.pollTimer = setInterval(refreshJobs, 2500);
boot();
