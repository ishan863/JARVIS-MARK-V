/* ── JARVIS Remote v3 — 3D Glassmorphism UI ── */

'use strict';

let ws = null, wsReconnectTimer = null, pin = '', paired = false;
let mediaRecorder = null, audioChunks = [], isRecording = false;
let desktopImgNaturalW = 0, desktopImgNaturalH = 0;
let desktopZoom = 1.0, desktopPanX = 0, desktopPanY = 0;
let lastTapTime = 0, longPressTimer = null, touchStartPos = null;
let isPanning = false, panStartX = 0, panStartY = 0;
let autoRefreshInterval = null, autoRefreshEnabled = false;
let typingTimeout = null, _pingStart = 0, _latencyHistory = [];
let _msgCallbacks = {}, _callbackId = 0, _recentCmds = [];
let _swipeStartX = 0, _swipeStartY = 0, _swipeStartTime = 0;

const SERVER_URL = `${location.protocol}//${location.host}`;
const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;
const TABS = ['chat','voice','desktop','tools','files'];

const ICON_MAP = {
  desktop: 'desktop_windows', downloads: 'download', documents: 'description',
  home: 'home', pictures: 'photo_library', music: 'music_note', videos: 'videocam',
};

// ── Init ──
window.addEventListener('load', () => {
  initThree();
  setupPinInputs();
  loadRecentCommands();
  loadChatHistory();
  const urlParams = new URLSearchParams(window.location.search);
  const urlPin = urlParams.get('pin');
  if (urlPin && urlPin.length === 4) {
    pin = urlPin; fillPinInputs(urlPin);
    localStorage.setItem('jarvis_pin', urlPin);
    setTimeout(() => { if (!paired) doPair(); }, 500);
  } else {
    const saved = localStorage.getItem('jarvis_pin');
    if (saved) { pin = saved; fillPinInputs(saved); }
  }
  connectWS();
  setupSwipe();
});

window.addEventListener('beforeunload', () => { stopAutoRefresh(); if (ws) ws.close(); });

// ── Three.js 3D Particle Background ──
function initThree() {
  try {
    const canvas = document.getElementById('bg-canvas');
    if (!canvas) return;
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 30;
    const geo = new THREE.BufferGeometry();
    const count = 120;
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count * 3; i++) pos[i] = (Math.random() - 0.5) * 80;
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0x2792ff, size: 0.15, transparent: true, opacity: 0.6,
      blending: THREE.AdditiveBlending,
    });
    const particles = new THREE.Points(geo, mat);
    scene.add(particles);
    function resize() {
      const w = window.innerWidth, h = window.innerHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    resize();
    window.addEventListener('resize', resize);
    let t = 0;
    function animate() {
      requestAnimationFrame(animate);
      t += 0.002;
      particles.rotation.x = Math.sin(t * 0.3) * 0.1;
      particles.rotation.y = t * 0.05;
      const p = particles.geometry.attributes.position.array;
      for (let i = 1; i < p.length; i += 3) p[i] += Math.sin(t + i) * 0.002;
      particles.geometry.attributes.position.needsUpdate = true;
      renderer.render(scene, camera);
    }
    animate();
  } catch (e) { /* Three.js not critical */ }
}

// ── WebSocket ──
function connectWS() {
  setStatus('connecting', 'Connecting…');
  try { ws = new WebSocket(WS_URL); } catch (e) { scheduleReconnect(); return; }
  ws.onopen = () => {
    setStatus('connected', 'Connected');
    clearTimeout(wsReconnectTimer);
    if (pin) sendPair(pin);
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    handleMsg(msg);
  };
  ws.onclose = () => { paired = false; setStatus('disconnected', 'Disconnected'); scheduleReconnect(); };
  ws.onerror = () => { ws.close(); };
}

function scheduleReconnect() { clearTimeout(wsReconnectTimer); wsReconnectTimer = setTimeout(connectWS, 3000); }
function wsSend(obj) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }

function registerCallback(type, fn, ttl) {
  const id = ++_callbackId;
  if (!_msgCallbacks[type]) _msgCallbacks[type] = {};
  _msgCallbacks[type][id] = fn;
  if (ttl) setTimeout(() => { delete _msgCallbacks[type][id]; }, ttl);
  return id;
}

function fireCallbacks(type, msg) {
  const cbs = _msgCallbacks[type];
  if (!cbs) return false;
  Object.values(cbs).forEach(fn => { try { fn(msg); } catch (e) { console.error(e); } });
  _msgCallbacks[type] = {};
  return true;
}

// ── Message handler ──
function handleMsg(msg) {
  if (fireCallbacks(msg.type, msg)) return;
  switch (msg.type) {
    case 'hello': if (pin) sendPair(pin); break;
    case 'paired':
      paired = true; setStatus('connected', 'Paired \u2713');
      document.getElementById('pair-screen').classList.remove('active');
      document.getElementById('app-screen').classList.add('active');
      addChatMsg('system', 'Connected to JARVIS');
      startAutoRefresh();
      break;
    case 'error':
      if (!paired) document.getElementById('pair-error').textContent = msg.data || 'Error';
      else addChatMsg('system', msg.data);
      break;
    case 'ai_text': hideTyping(); addChatMsg('ai', msg.data);
      document.getElementById('voice-transcript').textContent = msg.data; break;
    case 'ai_audio': hideTyping(); playAudio(msg.data); break;
    case 'file_list_result': renderFileList(msg.data); break;
    case 'file_download_result':
      if (msg.data) {
        const blob = b64ToBlob(msg.data, 'application/octet-stream');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'download'; a.click();
        URL.revokeObjectURL(url);
        addChatMsg('system', 'File downloaded');
      } else addChatMsg('system', 'File not found');
      break;
    case 'screenshot': showScreenshot(msg.data); break;
    case 'tool_result':
      document.getElementById('tool-result').textContent = msg.data || '(no output)';
      addChatMsg('ai', msg.data); break;
    case 'pong':
      if (_pingStart) {
        const lat = Date.now() - _pingStart;
        _latencyHistory.push(lat);
        if (_latencyHistory.length > 10) _latencyHistory.shift();
        updateLatency();
        _pingStart = 0;
      }
      break;
  }
}

// ── Pairing ──
function setupPinInputs() {
  const inputs = document.querySelectorAll('.pin-digit');
  inputs.forEach((inp, i) => {
    inp.addEventListener('input', () => {
      inp.value = inp.value.replace(/\D/g, '').slice(-1);
      if (inp.value && i < inputs.length - 1) inputs[i + 1].focus();
      if (i === inputs.length - 1 && inp.value) setTimeout(doPair, 100);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !inp.value && i > 0) inputs[i - 1].focus();
    });
  });
  inputs[0].focus();
}
function fillPinInputs(p) {
  document.querySelectorAll('.pin-digit').forEach((el, i) => { if (i < p.length) el.value = p[i]; });
}
function doPair() {
  const inputs = document.querySelectorAll('.pin-digit');
  pin = Array.from(inputs).map(i => i.value).join('');
  if (pin.length !== 4) { document.getElementById('pair-error').textContent = 'Enter all 4 digits'; return; }
  document.getElementById('pair-error').textContent = '';
  localStorage.setItem('jarvis_pin', pin);
  sendPair(pin);
}
function sendPair(p) {
  const info = getDeviceInfo();
  if ('getBattery' in navigator)
    navigator.getBattery().then(b => { info.battery = { level: Math.round(b.level * 100), charging: b.charging }; }).catch(()=>{});
  wsSend({ type: 'pair', pin: p, device_name: info.device, device_info: info });
}
function getDeviceInfo() {
  const screen = window.screen, conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  return {
    device: /iPhone/.test(navigator.userAgent) ? 'iPhone' : /iPad/.test(navigator.userAgent) ? 'iPad' : /Android/.test(navigator.userAgent) ? 'Android' : 'Mobile',
    userAgent: navigator.userAgent,
    screen: { width: screen.width, height: screen.height, orientation: screen.orientation ? screen.orientation.type : 'unknown', pixelRatio: window.devicePixelRatio || 1 },
    viewport: { width: window.innerWidth, height: window.innerHeight },
    platform: navigator.platform, language: navigator.language, online: navigator.onLine,
    connection: conn ? { effectiveType: conn.effectiveType, downlink: conn.downlink, rtt: conn.rtt } : null,
    battery: null, memory: navigator.deviceMemory || 'unknown', cores: navigator.hardwareConcurrency || 'unknown', touchPoints: navigator.maxTouchPoints || 0,
  };
}
function regeneratePin() { wsSend({ type: 'regenerate_pin' }); addChatMsg('system', 'Requesting new PIN…'); }

// ── Tab switching + Swipe ──
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  const contents = document.querySelectorAll('.tab-content');
  contents.forEach(c => {
    const isActive = c.id === 'tab-' + name;
    if (isActive) { c.classList.add('active'); c.style.transform = 'translateX(0) scale(1)'; c.style.opacity = '1'; }
    else { c.style.transform = 'translateX(20px) scale(0.97)'; c.style.opacity = '0'; }
  });
  if (name === 'desktop') refreshScreenshot();
}

function setupSwipe() {
  const container = document.getElementById('tab-container');
  if (!container) return;
  container.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    _swipeStartX = e.touches[0].clientX;
    _swipeStartY = e.touches[0].clientY;
    _swipeStartTime = Date.now();
  }, { passive: true });
  container.addEventListener('touchend', (e) => {
    if (!_swipeStartX) return;
    const dx = e.changedTouches[0].clientX - _swipeStartX;
    const dy = e.changedTouches[0].clientY - _swipeStartY;
    const dt = Date.now() - _swipeStartTime;
    _swipeStartX = 0;
    if (dt > 500 || Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    const current = document.querySelector('.tab-btn.active');
    if (!current) return;
    const idx = TABS.indexOf(current.dataset.tab);
    if (idx === -1) return;
    const next = dx < 0 ? Math.min(idx + 1, TABS.length - 1) : Math.max(idx - 1, 0);
    if (next !== idx) switchTab(TABS[next]);
  }, { passive: true });
}

// ── Chat ──
function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text || !paired) return;
  input.value = '';
  addToRecent(text);
  addChatMsg('user', text);
  saveChat();
  showTyping();
  wsSend({ type: 'text', data: text });
}

function addChatMsg(role, text) {
  const c = document.getElementById('chat-messages');
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.innerHTML = '<span class="msg-ts">' + fmtTime(new Date()) + '</span><span class="msg-text">' + escHtml(text) + '</span>';
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
  saveChat();
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function fmtTime(d) { return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0'); }

// ── Typing indicator ──
function showTyping() { const el = document.getElementById('typing-indicator'); if (el) el.classList.add('active'); clearTimeout(typingTimeout); typingTimeout = setTimeout(hideTyping, 15000); }
function hideTyping() { const el = document.getElementById('typing-indicator'); if (el) el.classList.remove('active'); clearTimeout(typingTimeout); }

// ── Chat history ──
function saveChat() {
  const items = [];
  document.querySelectorAll('#chat-messages .msg').forEach(el => {
    items.push({ role: el.className.replace('msg ',''), text: el.querySelector('.msg-text')?.textContent || '', ts: el.querySelector('.msg-ts')?.textContent || '' });
  });
  if (items.length > 100) items.splice(0, items.length - 100);
  try { localStorage.setItem('jarvis_chat', JSON.stringify(items)); } catch(e) {}
}
function loadChatHistory() {
  try {
    const raw = localStorage.getItem('jarvis_chat');
    if (!raw) return;
    JSON.parse(raw).forEach(item => {
      const d = document.createElement('div');
      d.className = 'msg ' + (item.role || 'system');
      d.innerHTML = '<span class="msg-ts">' + (item.ts || '') + '</span><span class="msg-text">' + escHtml(item.text || '') + '</span>';
      document.getElementById('chat-messages').appendChild(d);
    });
    document.getElementById('chat-messages').scrollTop = 99999;
  } catch(e) {}
}
function clearChatHistory() {
  localStorage.removeItem('jarvis_chat');
  document.getElementById('chat-messages').innerHTML = '';
  addChatMsg('system', 'Chat cleared');
}

// ── Recent commands ──
function loadRecentCommands() {
  try { _recentCmds = JSON.parse(localStorage.getItem('jarvis_recent')) || []; } catch(e) { _recentCmds = []; }
  if (!Array.isArray(_recentCmds)) _recentCmds = [];
  renderRecent();
}
function addToRecent(text) {
  _recentCmds = _recentCmds.filter(c => c !== text);
  _recentCmds.unshift(text);
  if (_recentCmds.length > 20) _recentCmds.length = 20;
  try { localStorage.setItem('jarvis_recent', JSON.stringify(_recentCmds)); } catch(e) {}
  renderRecent();
}
function renderRecent() {
  const c = document.getElementById('recent-cmds');
  if (!c) return;
  c.innerHTML = '';
  _recentCmds.slice(0, 8).forEach(cmd => {
    const chip = document.createElement('button');
    chip.className = 'recent-chip';
    chip.textContent = cmd;
    chip.addEventListener('click', () => { document.getElementById('chat-input').value = cmd; sendChat(); });
    c.appendChild(chip);
  });
}

// ── Voice ──
function toggleMic() {
  if (isRecording) { stopRecording(); return; }
  startRecording();
}

async function startRecording() {
  if (isRecording) return;
  const md = navigator.mediaDevices;
  if (!md || typeof md.getUserMedia !== 'function') {
    const el = document.getElementById('voice-status');
    if (location.protocol !== 'https:') {
      el.textContent = 'Scan the QR code — it now uses HTTPS for mic access.';
    } else if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
      el.textContent = 'iOS: accept the self-signed cert, then mic works.';
    } else {
      el.textContent = 'Mic API unavailable on this browser.';
    }
    return;
  }
  try {
    const stream = await md.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: getMime() });
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.start(100);
    isRecording = true;
    document.getElementById('mic-btn').classList.add('recording');
    document.getElementById('voice-status').textContent = 'Listening…';
    document.getElementById('voice-wave').classList.add('active');
    if (navigator.vibrate) navigator.vibrate(30);
  } catch (e) {
    const el = document.getElementById('voice-status');
    if (e.name === 'NotAllowedError') el.textContent = 'Mic permission denied';
    else if (e.name === 'NotFoundError') el.textContent = 'No microphone found';
    else el.textContent = 'Mic error: ' + e.message;
  }
}
function stopRecording() {
  if (!isRecording || !mediaRecorder) return;
  isRecording = false;
  mediaRecorder.stop();
  mediaRecorder.stream.getTracks().forEach(t => t.stop());
  document.getElementById('mic-btn').classList.remove('recording');
  document.getElementById('voice-status').textContent = 'Processing…';
  document.getElementById('voice-wave').classList.remove('active');
  if (navigator.vibrate) navigator.vibrate([20, 50, 20]);
  mediaRecorder.onstop = async () => {
    if (audioChunks.length < 1) { document.getElementById('voice-status').textContent = 'No audio detected'; return; }
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
    const b64 = await blob.arrayBuffer().then(buf => { let b='', u=new Uint8Array(buf); for(let i=0;i<u.byteLength;i++) b+=String.fromCharCode(u[i]); return btoa(b); });
    wsSend({ type: 'audio', data: b64, format: mediaRecorder.mimeType });
    showTyping();
    document.getElementById('voice-status').textContent = 'Sent — waiting…';
  };
}
function getMime() {
  for (const t of ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/mp4','audio/wav'])
    if (MediaRecorder.isTypeSupported(t)) return t;
  return '';
}
function b64ToBlob(b64, mime) {
  const bin = atob(b64), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return new Blob([u], { type: mime || 'application/octet-stream' });
}

// ── Audio playback ──
function playAudio(b64) {
  try { const a = new Audio(URL.createObjectURL(b64ToBlob(b64, 'audio/mpeg'))); a.play().catch(()=>{}); } catch(e) {}
}

// ── Desktop ──
function refreshScreenshot() { if (paired) wsSend({ type: 'screenshot' }); }
function zoomIn() { desktopZoom = Math.min(desktopZoom + 0.25, 4.0); applyTransform(); }
function zoomOut() { desktopZoom = Math.max(desktopZoom - 0.25, 0.5); applyTransform(); }
function resetZoom() { desktopZoom = 1.0; desktopPanX = 0; desktopPanY = 0; applyTransform(); }
function applyTransform() {
  document.getElementById('desktop-img').style.transform = 'scale(' + desktopZoom + ') translate(' + desktopPanX + 'px,' + desktopPanY + 'px)';
}
function showScreenshot(b64) {
  const img = document.getElementById('desktop-img'), ph = document.getElementById('desktop-placeholder');
  img.src = 'data:image/jpeg;base64,' + b64; img.style.display = 'block'; ph.style.display = 'none';
  img.onload = () => { desktopImgNaturalW = img.naturalWidth; desktopImgNaturalH = img.naturalHeight; applyTransform(); };
}
function handleDesktopClick(e) {
  e.preventDefault();
  if (desktopZoom > 1.0) return;
  const img = e.currentTarget, r = img.getBoundingClientRect(), ia = desktopImgNaturalW / desktopImgNaturalH, ba = r.width / r.height;
  let iw, ih, ox, oy;
  if (ia > ba) { iw = r.width; ih = r.width / ia; ox = 0; oy = (r.height - ih) / 2; }
  else { ih = r.height; iw = r.height * ia; ox = (r.width - iw) / 2; oy = 0; }
  const x = Math.max(0, Math.min(1, (e.clientX - r.left - ox) / iw));
  const y = Math.max(0, Math.min(1, (e.clientY - r.top - oy) / ih));
  const now = Date.now(), dbl = (now - lastTapTime) < 300;
  lastTapTime = now;
  wsSend({ type: 'click', x_pct: x, y_pct: y, button: dbl ? 'double' : 'left' });
  if (navigator.vibrate) navigator.vibrate(dbl ? [10,30,10] : 15);
  setTimeout(refreshScreenshot, 500);
}
// Desktop touch
window.addEventListener('load', () => {
  const img = document.getElementById('desktop-img');
  if (img) {
    let tx=0, ty=0;
    img.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      tx = e.touches[0].clientX; ty = e.touches[0].clientY;
      touchStartPos = { x: tx, y: ty };
      if (desktopZoom > 1.0) { isPanning = true; panStartX = desktopPanX; panStartY = desktopPanY; }
      else {
        longPressTimer = setTimeout(() => {
          const r = img.getBoundingClientRect(), ia = desktopImgNaturalW / desktopImgNaturalH, ba = r.width / r.height;
          let iw,ih,ox,oy;
          if (ia>ba){iw=r.width;ih=r.width/ia;ox=0;oy=(r.height-ih)/2}else{ih=r.height;iw=r.height*ia;ox=(r.width-iw)/2;oy=0}
          const x = Math.max(0,Math.min(1,(tx-r.left-ox)/iw)), y = Math.max(0,Math.min(1,(ty-r.top-oy)/ih));
          wsSend({type:'click',x_pct:x,y_pct:y,button:'right'});
          if (navigator.vibrate) navigator.vibrate([30,50,30]);
          longPressTimer = null;
          setTimeout(refreshScreenshot, 500);
        }, 600);
      }
    }, { passive: false });
    img.addEventListener('touchend', () => { if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer=null; } isPanning=false; }, { passive: false });
    img.addEventListener('touchmove', (e) => {
      if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer=null; }
      if (isPanning && e.touches.length===1 && desktopZoom>1.0) {
        e.preventDefault();
        desktopPanX = panStartX + (e.touches[0].clientX - tx) / desktopZoom;
        desktopPanY = panStartY + (e.touches[0].clientY - ty) / desktopZoom;
        applyTransform();
      }
    }, { passive: false });
  }
});
function sendTypeToDesktop() {
  const input = document.getElementById('desktop-type-input'), text = input.value;
  if (!text || !paired) return; input.value = ''; wsSend({ type: 'type', data: text });
}
function sendKey(key) { if (!paired) return; wsSend({ type: 'key', data: key }); setTimeout(refreshScreenshot, 400); }
function sendScroll(dir, amt) { if (!paired) return; wsSend({ type: 'scroll', direction: dir, amount: amt }); setTimeout(refreshScreenshot, 400); }

// ── Auto-refresh ──
function startAutoRefresh() {
  if (autoRefreshInterval) return;
  autoRefreshEnabled = true;
  autoRefreshInterval = setInterval(() => {
    const active = document.querySelector('.tab-content.active');
    if (active && active.id === 'tab-desktop' && paired && autoRefreshEnabled) refreshScreenshot();
  }, 3000);
}
function stopAutoRefresh() { autoRefreshEnabled = false; if (autoRefreshInterval) { clearInterval(autoRefreshInterval); autoRefreshInterval=null; } }
function toggleAutoRefresh() { if (autoRefreshEnabled) { stopAutoRefresh(); addChatMsg('system','Auto-refresh OFF'); } else { startAutoRefresh(); addChatMsg('system','Auto-refresh ON (3s)'); } }

// ── Tools ──
function sendDeviceInfo() {
  if (!paired) return;
  const info = getDeviceInfo();
  const send = (bat) => {
    if (bat) info.battery = bat;
    const text = 'Device Info:\nDevice: ' + info.device + '\nScreen: ' + info.screen.width + 'x' + info.screen.height + ' @ ' + info.screen.pixelRatio + 'x\nOrientation: ' + info.screen.orientation + '\nViewport: ' + info.viewport.width + 'x' + info.viewport.height + '\nPlatform: ' + info.platform + '\nLanguage: ' + info.language + '\nOnline: ' + info.online + (info.battery ? '\nBattery: ' + info.battery.level + '%' + (info.battery.charging ? ' (charging)' : '') : '') + '\nMemory: ' + info.memory + ' GB\nCPU: ' + info.cores + ' cores\nTouch: ' + info.touchPoints + ' pts' + (info.connection ? '\nNetwork: ' + info.connection.effectiveType + ' (' + info.connection.downlink + ' Mbps)' : '');
    wsSend({ type: 'text', data: text }); addChatMsg('user', text); switchTab('chat');
  };
  if ('getBattery' in navigator) navigator.getBattery().then(b => send({level:Math.round(b.level*100),charging:b.charging})).catch(()=>send(null));
  else send(null);
}
function quickTool(tool, params) { if (!paired) return; document.getElementById('tool-result').textContent = 'Running…'; wsSend({ type: 'tool', tool, params }); if (navigator.vibrate) navigator.vibrate(20); }
function sendCustomCmd() {
  const input = document.getElementById('custom-cmd'), text = input.value.trim();
  if (!text || !paired) return; input.value = '';
  addToRecent(text); addChatMsg('user', text); showTyping(); wsSend({ type: 'text', data: text }); switchTab('chat');
}

// ── Files ──
function listFiles(folder) {
  if (!paired) return;
  document.getElementById('files-list').innerHTML = '<div class="muted-text"><span class="material-symbols-outlined" style="font-size:32px;display:block;margin-bottom:8px">hourglass_top</span>Loading…</div>';
  wsSend({ type: 'file_list', data: folder });
}
function renderFileList(text) {
  const c = document.getElementById('files-list');
  if (!text || text === '(empty)') { c.innerHTML = '<div class="muted-text">Empty folder</div>'; return; }
  if (text.startsWith('Error') || text.startsWith("Folder '")) { c.innerHTML = '<div class="muted-text">' + escHtml(text) + '</div>'; return; }
  c.innerHTML = '';
  text.split('\n').filter(l => l.trim()).forEach(line => {
    const item = document.createElement('div');
    item.className = 'file-item';
    const isDir = line.includes('/');
    const name = line.replace(/\s+\[.*?\]\s*$/, '').trim();
    const size = (line.match(/\[(.*?)\]/)||[])[1] || '';
    item.innerHTML = '<span class="material-symbols-outlined file-icon">' + (isDir ? 'folder' : 'description') + '</span><span class="file-name">' + escHtml(name) + '</span><span class="file-size">' + escHtml(size) + '</span>';
    if (isDir) {
      item.addEventListener('click', () => {
        const dirKey = Object.keys(ICON_MAP).find(k => k === name.replace('/',''));
        if (dirKey) listFiles(dirKey);
      });
    } else {
      item.addEventListener('click', () => {
        const m = line.match(/^(.*?)\s+\[/);
        if (m) { wsSend({ type: 'file_download', data: m[1].trim() }); addChatMsg('system', 'Downloading: ' + m[1].trim()); }
      });
    }
    c.appendChild(item);
  });
}
function triggerFileUpload() { document.getElementById('file-upload-input')?.click(); }
async function handleFileSelected(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const fd = new FormData(); fd.append('file', file); fd.append('pin', pin);
  try {
    const r = await fetch(SERVER_URL + '/api/upload', { method: 'POST', body: fd });
    const result = await r.json();
    if (result.status === 'saved') addChatMsg('system', 'Uploaded: ' + file.name + ' (' + result.bytes + ' B)');
    else addChatMsg('system', 'Upload failed: ' + (result.error || 'unknown'));
  } catch (err) { addChatMsg('system', 'Upload error'); }
  e.target.value = '';
}

// ── Status ──
function setStatus(state, text) {
  const dot = document.getElementById('ws-dot'), label = document.getElementById('status-text');
  const badge = document.getElementById('status-badge');
  if (dot) dot.className = 'ws-dot ' + state;
  if (label) label.textContent = text;
  if (badge) {
    badge.textContent = text;
    badge.className = 'status-badge ' + state;
  }
}

// ── Latency ──
function updateLatency() {
  if (!_latencyHistory.length) return;
  const avg = _latencyHistory.reduce((a,b)=>a+b,0) / _latencyHistory.length;
  const el = document.getElementById('latency-indicator');
  if (el) { el.textContent = Math.round(avg) + 'ms'; el.className = 'latency-indicator latency-' + (avg < 100 ? 'good' : avg < 300 ? 'ok' : 'bad'); }
}
function measureLatency() { if (ws && ws.readyState === WebSocket.OPEN) { _pingStart = Date.now(); wsSend({ type: 'ping' }); } }

// ── Keepalive ──
setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) measureLatency(); }, 25000);
