// Record page logic: keyboard-first recorder with a fixed layout.
renderNav('record');

const $ = (id) => document.getElementById(id);
const els = {
  idChip: $('idChip'), idxChip: $('idxChip'), statusChip: $('statusChip'), sentence: $('sentence'),
  tamang: $('tamang'), metaRow: $('metaRow'), flagbox: $('flagbox'), canvas: $('wave'), overlay: $('waveOverlay'),
  timer: $('timer'), stateText: $('stateText'), meter: $('meter'), prev: $('prevBtn'), redo: $('redoBtn'),
  rec: $('recBtn'), recLabel: $('recLabel'), play: $('playBtn'), save: $('saveBtn'), next: $('nextBtn'),
  autoSave: $('autoSave'), showTamang: $('showTamang'), player: $('player'),
  jumpForm: $('jumpForm'), jumpInput: $('jumpInput'),
};

// ---------------------------------------------------------------- state
let cur = null;                 // current sentence payload
let mode = 'idle';              // idle | recording | take | saving
let stream = null, actx = null, analyser = null, mediaRec = null, chunks = [];
let recStart = 0, livePeaks = [], clipDuringTake = false;
let takeBlob = null, takeUrl = null, takeDur = 0;
let staticPeaks = null;         // waveform of take or saved clip
let decodeCtx = null;

els.autoSave.checked = localStorage.getItem('autoSave') === '1';
els.showTamang.checked = localStorage.getItem('showTamang') === '1';
els.autoSave.addEventListener('change', () => localStorage.setItem('autoSave', els.autoSave.checked ? '1' : '0'));
els.showTamang.addEventListener('change', () => { localStorage.setItem('showTamang', els.showTamang.checked ? '1' : '0'); applyTamang(); });
function applyTamang() { els.tamang.classList.toggle('hidden', !els.showTamang.checked); }
applyTamang();

// ---------------------------------------------------------------- mic
async function ensureMic() {
  if (stream) { if (actx.state === 'suspended') await actx.resume(); return; }
  // Raw capture: no browser processing, so the dataset stays clean and consistent.
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
  });
  actx = new AudioContext();
  const src = actx.createMediaStreamSource(stream);
  analyser = actx.createAnalyser();
  analyser.fftSize = 2048;
  src.connect(analyser);
}

function pickMime() {
  const c = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  return c.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
}

// ---------------------------------------------------------------- recording
async function startRecording() {
  if (mode === 'recording' || mode === 'saving' || !cur) return;
  try { await ensureMic(); } catch (e) { toast('Microphone blocked: ' + e.message, 'err', 5000); return; }
  stopPlayback();
  discardTake();
  const mime = pickMime();
  mediaRec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 256000 } : undefined);
  chunks = [];
  mediaRec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  mediaRec.onstop = onRecorderStop;
  livePeaks = []; clipDuringTake = false;
  mediaRec.start();
  recStart = performance.now();
  setMode('recording');
}

function stopRecording() {
  if (mode !== 'recording') return;
  takeDur = (performance.now() - recStart) / 1000;
  mediaRec.stop();
}

async function onRecorderStop() {
  if (takeDur < 0.5) {
    chunks = [];
    setMode(cur && cur.recorded ? 'idle' : 'idle');
    toast('Too short — ignored. Hold a bit longer.', 'warn');
    showSavedWave();
    return;
  }
  takeBlob = new Blob(chunks, { type: mediaRec.mimeType || 'audio/webm' });
  takeUrl = URL.createObjectURL(takeBlob);
  setMode('take');
  staticPeaks = await peaksFromBlob(takeBlob).catch(() => null);
  if (clipDuringTake) toast('Input clipped — move back from the mic and redo.', 'warn', 4500);
  if (els.autoSave.checked) save();
}

function discardTake() {
  if (takeUrl) URL.revokeObjectURL(takeUrl);
  takeBlob = null; takeUrl = null; takeDur = 0;
}

// ---------------------------------------------------------------- save / nav
async function save() {
  if (mode !== 'take' || !takeBlob || !cur) return;
  setMode('saving');
  const fd = new FormData();
  const ext = (takeBlob.type.includes('mp4') ? 'm4a' : takeBlob.type.includes('ogg') ? 'ogg' : 'webm');
  fd.append('file', takeBlob, `take.${ext}`);
  try {
    const r = await api(`/api/record/${encodeURIComponent(cur.id)}`, { method: 'POST', body: fd });
    discardTake();
    setMode('idle');
    updateNavProgress(r.recorded_count, cur.total);
    const serious = r.meta.flags.filter((f) => ['silent', 'clipped', 'quiet', 'short'].includes(f));
    if (serious.length) {
      toast(`Saved ${cur.id}, but: ${serious.map((f) => FLAG_LABELS[f]).join(', ')}. Press R/Space to redo or ⏎ to continue.`, 'warn', 6000);
      await load({ id: cur.id });
    } else {
      toast(`Saved ${cur.id}.mp3 · ${r.meta.duration.toFixed(1)}s`, 'ok', 1800);
      if (r.next_unrecorded === null) { await load({ id: cur.id }); toast('🎉 All sentences recorded!', 'ok', 6000); }
      else await load({ idx: r.next_unrecorded });
    }
  } catch (e) {
    setMode('take');
    toast('Save failed: ' + e.message, 'err', 6000);
  }
}

async function load(q) {
  if (mode === 'recording') return;
  stopPlayback();
  discardTake();
  const qs = q && q.id !== undefined ? `id=${encodeURIComponent(q.id)}` : q && q.idx !== undefined ? `idx=${q.idx}` : '';
  try {
    cur = await api(`/api/sentence?${qs}`);
  } catch (e) { toast(e.message, 'err'); return; }
  history.replaceState(null, '', `/record?id=${encodeURIComponent(cur.id)}`);
  render();
  setMode('idle');
  showSavedWave();
}

function go(delta) {
  if (!cur) return;
  const i = cur.idx + delta;
  if (i < 0 || i >= cur.total) return;
  load({ idx: i });
}

function goNextPending() {
  if (!cur) return;
  if (cur.next_unrecorded === null) { toast('Everything is recorded 🎉'); return; }
  load({ idx: cur.next_unrecorded });
}

async function redo() {
  if (mode === 'recording') { // cancel in-progress take
    mediaRec.onstop = () => { chunks = []; setMode('idle'); showSavedWave(); };
    mediaRec.stop();
    return;
  }
  if (mode === 'take') { discardTake(); setMode('idle'); showSavedWave(); toast('Take discarded', 'warn', 1200); return; }
  if (mode === 'idle' && cur && cur.recorded) startRecording();
}

// ---------------------------------------------------------------- playback
function togglePlay() {
  const p = els.player;
  if (!p.paused) { p.pause(); return; }
  let src = null;
  if (mode === 'take' && takeUrl) src = takeUrl;
  else if (mode === 'idle' && cur && cur.recorded) src = `/api/audio/${encodeURIComponent(cur.id)}?t=${Date.now()}`;
  if (!src) return;
  if (p.dataset.src !== src || p.ended) { p.src = src; p.dataset.src = src; }
  p.play().catch(() => {});
}
function stopPlayback() { els.player.pause(); els.player.removeAttribute('src'); els.player.dataset.src = ''; }
els.player.addEventListener('play', () => (els.play.textContent = '❚❚ Pause'));
els.player.addEventListener('pause', () => (els.play.textContent = '▶ Play'));
els.player.addEventListener('ended', () => (els.play.textContent = '▶ Play'));

// ---------------------------------------------------------------- render
function render() {
  els.idChip.textContent = cur.id;
  els.idxChip.textContent = `#${(cur.idx + 1).toLocaleString()} / ${cur.total.toLocaleString()}`;
  els.sentence.textContent = cur.nepali;
  els.sentence.classList.toggle('long', cur.nepali.length > 80);
  els.tamang.textContent = cur.tamang || '—';
  els.metaRow.innerHTML = [cur.type, cur.tense, cur.polarity].map((v, i) =>
    `<span class="chip">${['Type', 'Tense', 'Polarity'][i]}: ${v}</span>`).join('');
  const flags = (cur.meta && cur.meta.flags) || [];
  els.flagbox.innerHTML = flags.map((f) => `<span class="chip flag">⚠ ${FLAG_LABELS[f] || f}</span>`).join('');
  updateNavProgress(cur.recorded_count, cur.total);
}

function setMode(m) {
  mode = m;
  const rec = m === 'recording', take = m === 'take', saving = m === 'saving';
  els.rec.classList.toggle('recording', rec);
  els.rec.classList.toggle('idle', !rec);
  els.recLabel.textContent = rec ? 'Stop' : (take || (cur && cur.recorded) ? 'Re-record' : 'Record');
  els.prev.disabled = rec || saving || !cur || cur.idx === 0;
  els.next.disabled = rec || saving || !cur || cur.idx >= cur.total - 1;
  els.redo.disabled = !(rec || take || (m === 'idle' && cur && cur.recorded));
  els.play.disabled = !(take || (m === 'idle' && cur && cur.recorded));
  els.save.disabled = !(take || (m === 'idle' && cur && cur.recorded));
  els.save.innerHTML = take || saving ? (saving ? 'Saving…' : 'Save &amp; Next <span class="kbd">⏎</span>')
                                      : 'Next pending <span class="kbd">⏎</span>';
  els.rec.disabled = saving;

  let chip = ['pending', 'Pending'];
  if (take || saving) chip = ['pending', 'Unsaved take'];
  else if (cur && cur.recorded) chip = ['ok', '✓ Recorded'];
  if (rec) chip = ['flag', '● Recording'];
  els.statusChip.className = `chip ${chip[0]}`;
  els.statusChip.textContent = chip[1];

  const st = {
    idle: cur && cur.recorded ? `<b>Saved</b> · ${cur.meta ? cur.meta.duration.toFixed(1) + 's' : ''} — Space to re-record, ⏎ for next pending`
                              : 'Ready — press <b>Space</b> and read the sentence',
    recording: '<b>Recording…</b> press Space to stop',
    take: els.autoSave.checked ? 'Saving…' : '<b>Take ready</b> — ⏎ save · P play · Space/R redo',
    saving: 'Cleaning &amp; saving…',
  }[m];
  els.stateText.innerHTML = st;
  els.overlay.style.display = (m === 'idle' && !(cur && cur.recorded)) ? 'grid' : 'none';
  if (m === 'idle') els.timer.textContent = fmtTimer(cur && cur.meta ? cur.meta.duration : 0);
  if (take) els.timer.textContent = fmtTimer(takeDur);
}

function fmtTimer(s) {
  const m = Math.floor(s / 60), r = s - m * 60;
  return `${String(m).padStart(2, '0')}:${r.toFixed(1).padStart(4, '0')}`;
}

// ---------------------------------------------------------------- waveform
const ctx2d = els.canvas.getContext('2d');
function sizeCanvas() {
  const dpr = window.devicePixelRatio || 1, r = els.canvas.getBoundingClientRect();
  els.canvas.width = Math.round(r.width * dpr); els.canvas.height = Math.round(r.height * dpr);
}
window.addEventListener('resize', sizeCanvas); sizeCanvas();

async function peaksFromBlob(blob) {
  decodeCtx = decodeCtx || new AudioContext();
  const buf = await decodeCtx.decodeAudioData(await blob.arrayBuffer());
  const data = buf.getChannelData(0), n = 220, step = Math.max(1, Math.floor(data.length / n)), out = [];
  for (let i = 0; i < n; i++) {
    let mx = 0; const s = i * step, e = Math.min(data.length, s + step);
    for (let j = s; j < e; j++) { const v = Math.abs(data[j]); if (v > mx) mx = v; }
    out.push(mx);
  }
  return out;
}

async function showSavedWave() {
  staticPeaks = null;
  if (!cur || !cur.recorded) return;
  const id = cur.id;
  try {
    const blob = await (await fetch(`/api/audio/${encodeURIComponent(id)}?t=${Date.now()}`)).blob();
    const p = await peaksFromBlob(blob);
    if (cur && cur.id === id && mode === 'idle') staticPeaks = p;
  } catch (_) {}
}

function drawBars(peaks, progress, color) {
  const W = els.canvas.width, H = els.canvas.height, n = peaks.length;
  const bw = W / n, mid = H / 2, gap = Math.max(1, bw * 0.3);
  const max = Math.max(0.05, ...peaks);
  for (let i = 0; i < n; i++) {
    const h = Math.max(2, (peaks[i] / max) * (H * 0.84));
    ctx2d.fillStyle = (progress !== null && i / n <= progress) ? '#7dd3fc' : color;
    ctx2d.fillRect(i * bw + gap / 2, mid - h / 2, bw - gap, h);
  }
}

const tbuf = new Float32Array(2048);
function frame() {
  const W = els.canvas.width, H = els.canvas.height;
  ctx2d.clearRect(0, 0, W, H);
  ctx2d.fillStyle = 'rgba(148,163,184,.12)'; ctx2d.fillRect(0, H / 2, W, 1);

  let peak = 0;
  if (analyser) {
    analyser.getFloatTimeDomainData(tbuf);
    for (let i = 0; i < tbuf.length; i++) { const v = Math.abs(tbuf[i]); if (v > peak) peak = v; }
    const dbv = 20 * Math.log10(Math.max(peak, 1e-5));
    els.meter.style.width = `${Math.min(100, Math.max(0, (dbv + 60) / 60 * 100))}%`;
  }

  if (mode === 'recording') {
    livePeaks.push(peak);
    if (peak >= 0.99) clipDuringTake = true;
    const n = Math.floor(W / (4 * (window.devicePixelRatio || 1)));
    const view = livePeaks.slice(-n);
    while (view.length < n) view.unshift(0);
    const bw = W / n, mid = H / 2;
    for (let i = 0; i < n; i++) {
      const h = Math.max(2, Math.min(1, view[i] * 1.6) * H * 0.88);
      ctx2d.fillStyle = `hsla(352, 90%, ${55 + (i / n) * 15}%, ${0.35 + 0.65 * (i / n)})`;
      ctx2d.fillRect(i * bw + 1, mid - h / 2, bw - 2, h);
    }
    els.timer.textContent = fmtTimer((performance.now() - recStart) / 1000);
  } else if (staticPeaks) {
    const p = els.player;
    const prog = !p.paused && p.duration ? p.currentTime / p.duration : null;
    drawBars(staticPeaks, prog, mode === 'take' || mode === 'saving' ? 'rgba(167,139,250,.9)' : 'rgba(74,222,128,.75)');
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------- input
els.rec.addEventListener('click', () => (mode === 'recording' ? stopRecording() : startRecording()));
els.redo.addEventListener('click', redo);
els.play.addEventListener('click', togglePlay);
els.save.addEventListener('click', () => (mode === 'take' ? save() : goNextPending()));
els.prev.addEventListener('click', () => go(-1));
els.next.addEventListener('click', () => go(1));
els.jumpForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const v = els.jumpInput.value.trim();
  if (!v) return;
  els.jumpInput.blur();
  if (/^\d+$/.test(v)) load({ idx: parseInt(v, 10) - 1 }); else load({ id: v });
  els.jumpInput.value = '';
});

window.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (e.code === 'Space') {
    e.preventDefault();
    if (e.repeat) return;
    mode === 'recording' ? stopRecording() : startRecording();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (mode === 'take') save(); else if (mode === 'idle') goNextPending();
  } else if (k === 'r') { e.preventDefault(); redo(); }
  else if (k === 'p') { e.preventDefault(); togglePlay(); }
  else if (k === 'n') { e.preventDefault(); goNextPending(); }
  else if (k === 't') { els.showTamang.checked = !els.showTamang.checked; els.showTamang.dispatchEvent(new Event('change')); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
});

window.addEventListener('beforeunload', (e) => { if (mode === 'take' || mode === 'recording') { e.preventDefault(); e.returnValue = ''; } });

// ---------------------------------------------------------------- boot
const params = new URLSearchParams(location.search);
load(params.get('id') ? { id: params.get('id') } : params.get('idx') ? { idx: +params.get('idx') } : {});
