/* ── JARVIS Remote — WebSocket client + UI logic ── */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let ws = null;
let wsReconnectTimer = null;
let pin = '';
let paired = false;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let desktopImgNaturalW = 0;
let desktopImgNaturalH = 0;

// Auto-detect server URL from current page origin
const SERVER_URL = `${location.protocol}//${location.host}`;
const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`;

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  setupPinInputs();
  // Auto-fill PIN from URL query param (QR code scan)
  const urlParams = new URLSearchParams(window.location.search);
  const urlPin = urlParams.get('pin');
  if (urlPin && urlPin.length === 4) {
    pin = urlPin;
    fillPinInputs(urlPin);
    localStorage.setItem('jarvis_pin', urlPin);
    // Auto-connect after 500ms
    setTimeout(() => {
      if (!paired) doPair();
    }, 500);
  } else {
    // Try to restore PIN from localStorage
    const savedPin = localStorage.getItem('jarvis_pin');
    if (savedPin) {
      pin = savedPin;
      fillPinInputs(savedPin);
    }
  }
  connectWS();
});

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWS() {
  setStatus('connecting', 'Connecting…');
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    setStatus('connected', 'Connected');
    clearTimeout(wsReconnectTimer);
    if (pin) {
      sendPair(pin);
    }
  };

  ws.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch { return; }
    handleServerMessage(msg);
  };

  ws.onclose = () => {
    paired = false;
    setStatus('disconnected', 'Disconnected');
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  clearTimeout(wsReconnectTimer);
  wsReconnectTimer = setTimeout(connectWS, 3000);
}

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

// ── Server message handler ─────────────────────────────────────────────────
function handleServerMessage(msg) {
  switch (msg.type) {
    case 'hello':
      // Server greeted us — send PIN if we have one
      if (pin) sendPair(pin);
      break;

    case 'paired':
      paired = true;
      setStatus('connected', 'Paired ✓');
      showApp();
      addChatMsg('system', '✅ Connected to JARVIS');
      break;

    case 'error':
      if (!paired) {
        document.getElementById('pair-error').textContent = msg.data || 'Error';
      } else {
        addChatMsg('system', '⚠️ ' + msg.data);
      }
      break;

    case 'ai_text':
      addChatMsg('ai', msg.data);
      document.getElementById('voice-transcript').textContent = msg.data;
      break;

    case 'ai_audio':
      playBase64Audio(msg.data);
      break;

    case 'log':
      // Optionally show log lines in chat
      break;

    case 'screenshot':
      showScreenshot(msg.data);
      break;

    case 'tool_result':
      document.getElementById('tool-result').textContent = msg.data || '(no output)';
      addChatMsg('ai', msg.data);
      break;

    case 'click_result':
    case 'type_result':
    case 'key_result':
    case 'scroll_result':
      // Silent ack
      break;

    case 'ack':
      break;

    case 'pong':
      break;
  }
}

// ── Pairing ────────────────────────────────────────────────────────────────
function setupPinInputs() {
  const inputs = document.querySelectorAll('.pin-digit');
  inputs.forEach((inp, i) => {
    inp.addEventListener('input', () => {
      inp.value = inp.value.replace(/\D/g, '').slice(-1);
      if (inp.value && i < inputs.length - 1) {
        inputs[i + 1].focus();
      }
      if (i === inputs.length - 1 && inp.value) {
        // Auto-submit when last digit entered
        setTimeout(doPair, 100);
      }
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !inp.value && i > 0) {
        inputs[i - 1].focus();
      }
    });
  });
  inputs[0].focus();
}

function fillPinInputs(p) {
  const inputs = document.querySelectorAll('.pin-digit');
  for (let i = 0; i < Math.min(p.length, inputs.length); i++) {
    inputs[i].value = p[i];
  }
}

function doPair() {
  const inputs = document.querySelectorAll('.pin-digit');
  pin = Array.from(inputs).map(i => i.value).join('');
  if (pin.length !== 4) {
    document.getElementById('pair-error').textContent = 'Enter all 4 digits';
    return;
  }
  document.getElementById('pair-error').textContent = '';
  localStorage.setItem('jarvis_pin', pin);
  sendPair(pin);
}

function sendPair(p) {
  const deviceInfo = getDeviceInfo();
  
  // Try to get battery info
  if ('getBattery' in navigator) {
    navigator.getBattery().then(battery => {
      deviceInfo.battery = {
        level: Math.round(battery.level * 100),
        charging: battery.charging
      };
    }).catch(() => {});
  }
  
  wsSend({ 
    type: 'pair', 
    pin: p, 
    device_name: deviceInfo.device,
    device_info: deviceInfo
  });
}

function getDeviceName() {
  const ua = navigator.userAgent;
  let device = 'Mobile';
  
  if (/iPhone/.test(ua)) device = 'iPhone';
  else if (/iPad/.test(ua)) device = 'iPad';
  else if (/Android/.test(ua)) device = 'Android';
  
  return device;
}

function getDeviceInfo() {
  const ua = navigator.userAgent;
  const screen = window.screen;
  const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  
  return {
    device: getDeviceName(),
    userAgent: ua,
    screen: {
      width: screen.width,
      height: screen.height,
      orientation: screen.orientation ? screen.orientation.type : 'unknown',
      pixelRatio: window.devicePixelRatio || 1
    },
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight
    },
    platform: navigator.platform,
    language: navigator.language,
    online: navigator.onLine,
    connection: connection ? {
      effectiveType: connection.effectiveType,
      downlink: connection.downlink,
      rtt: connection.rtt
    } : null,
    battery: null, // Will be populated async
    memory: navigator.deviceMemory || 'unknown',
    cores: navigator.hardwareConcurrency || 'unknown',
    touchPoints: navigator.maxTouchPoints || 0
  };
}

function showApp() {
  document.getElementById('pair-screen').classList.remove('active');
  document.getElementById('app-screen').classList.add('active');
}

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + name));
  if (name === 'desktop') {
    refreshScreenshot();
  }
}

// ── Chat ───────────────────────────────────────────────────────────────────
function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text || !paired) return;
  input.value = '';
  addChatMsg('user', text);
  wsSend({ type: 'text', data: text });
}

function addChatMsg(role, text) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ── Voice ──────────────────────────────────────────────────────────────────
async function startRecording() {
  if (isRecording) return;
  try {
    // Request microphone permission with better error handling
    const stream = await navigator.mediaDevices.getUserMedia({ 
      audio: { 
        sampleRate: 16000, 
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      } 
    });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: getSupportedMimeType() });
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.start(100);
    isRecording = true;

    const btn = document.getElementById('mic-btn');
    btn.classList.add('recording');
    document.getElementById('voice-status').textContent = 'Listening…';
    document.getElementById('voice-wave').classList.add('active');
    if (navigator.vibrate) navigator.vibrate(30);
  } catch (e) {
    console.error('Microphone error:', e);
    const statusEl = document.getElementById('voice-status');
    if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
      statusEl.textContent = '⚠️ Mic permission denied';
      addChatMsg('system', '🎤 Please allow microphone access in Settings → Safari → Microphone');
    } else if (e.name === 'NotFoundError') {
      statusEl.textContent = '⚠️ No microphone found';
    } else {
      statusEl.textContent = '⚠️ Mic error: ' + e.message;
    }
  }
}

function stopRecording() {
  if (!isRecording || !mediaRecorder) return;
  isRecording = false;
  mediaRecorder.stop();
  mediaRecorder.stream.getTracks().forEach(t => t.stop());

  const btn = document.getElementById('mic-btn');
  btn.classList.remove('recording');
  document.getElementById('voice-status').textContent = 'Processing…';
  document.getElementById('voice-wave').classList.remove('active');
  if (navigator.vibrate) navigator.vibrate([20, 50, 20]);

  mediaRecorder.onstop = async () => {
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
    const arrayBuf = await blob.arrayBuffer();
    const b64 = arrayBufferToBase64(arrayBuf);
    wsSend({ type: 'audio', data: b64, format: 'wav' });
    document.getElementById('voice-status').textContent = 'Sent — waiting for response…';
  };
}

function getSupportedMimeType() {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  for (const t of types) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return '';
}

function arrayBufferToBase64(buf) {
  let binary = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

// ── Audio playback ─────────────────────────────────────────────────────────
function playBase64Audio(b64) {
  try {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play().catch(() => {});
    audio.onended = () => URL.revokeObjectURL(url);
  } catch (e) {}
}

// ── Desktop ────────────────────────────────────────────────────────────────
let desktopZoom = 1.0;
let desktopPanX = 0;
let desktopPanY = 0;

function refreshScreenshot() {
  if (!paired) return;
  wsSend({ type: 'screenshot' });
}

function zoomIn() {
  desktopZoom = Math.min(desktopZoom + 0.25, 4.0);
  applyDesktopTransform();
}

function zoomOut() {
  desktopZoom = Math.max(desktopZoom - 0.25, 0.5);
  applyDesktopTransform();
}

function resetZoom() {
  desktopZoom = 1.0;
  desktopPanX = 0;
  desktopPanY = 0;
  applyDesktopTransform();
}

function applyDesktopTransform() {
  const img = document.getElementById('desktop-img');
  img.style.transform = `scale(${desktopZoom}) translate(${desktopPanX}px, ${desktopPanY}px)`;
  img.style.transformOrigin = 'center';
}

function showScreenshot(b64) {
  const img = document.getElementById('desktop-img');
  const placeholder = document.getElementById('desktop-placeholder');
  img.src = 'data:image/jpeg;base64,' + b64;
  img.style.display = 'block';
  placeholder.style.display = 'none';
  img.onload = () => {
    desktopImgNaturalW = img.naturalWidth;
    desktopImgNaturalH = img.naturalHeight;
    applyDesktopTransform();
  };
}

// Desktop touch/click handling with right-click and double-click support
let lastTapTime = 0;
let longPressTimer = null;
let touchStartPos = null;
let isPanning = false;
let panStartX = 0;
let panStartY = 0;

function handleDesktopClick(event) {
  // Prevent default to avoid iOS zoom/scroll
  event.preventDefault();
  
  if (desktopZoom > 1.0) {
    // In zoom mode, don't click - just pan
    return;
  }
  
  const img = event.currentTarget;
  const rect = img.getBoundingClientRect();
  const displayW = rect.width;
  const displayH = rect.height;

  // Account for letterboxing (object-fit: contain)
  const imgAspect = desktopImgNaturalW / desktopImgNaturalH;
  const boxAspect = displayW / displayH;
  let imgW, imgH, offsetX, offsetY;
  if (imgAspect > boxAspect) {
    imgW = displayW;
    imgH = displayW / imgAspect;
    offsetX = 0;
    offsetY = (displayH - imgH) / 2;
  } else {
    imgH = displayH;
    imgW = displayH * imgAspect;
    offsetX = (displayW - imgW) / 2;
    offsetY = 0;
  }

  const clickX = event.clientX - rect.left - offsetX;
  const clickY = event.clientY - rect.top - offsetY;
  const x_pct = Math.max(0, Math.min(1, clickX / imgW));
  const y_pct = Math.max(0, Math.min(1, clickY / imgH));

  // Detect double-tap
  const now = Date.now();
  const isDoubleTap = (now - lastTapTime) < 300;
  lastTapTime = now;

  const button = isDoubleTap ? 'double' : 'left';
  wsSend({ type: 'click', x_pct, y_pct, button });
  if (navigator.vibrate) navigator.vibrate(isDoubleTap ? [10, 30, 10] : 15);

  // Auto-refresh after click
  setTimeout(refreshScreenshot, 500);
}

function handleDesktopTouchStart(event) {
  event.preventDefault();
  
  if (event.touches.length === 1) {
    const touch = event.touches[0];
    touchStartPos = { x: touch.clientX, y: touch.clientY };
    
    if (desktopZoom > 1.0) {
      // Pan mode
      isPanning = true;
      panStartX = desktopPanX;
      panStartY = desktopPanY;
    } else {
      // Long-press for right-click
      longPressTimer = setTimeout(() => {
        const img = event.currentTarget;
        const rect = img.getBoundingClientRect();
        const displayW = rect.width;
        const displayH = rect.height;
        const imgAspect = desktopImgNaturalW / desktopImgNaturalH;
        const boxAspect = displayW / displayH;
        let imgW, imgH, offsetX, offsetY;
        if (imgAspect > boxAspect) {
          imgW = displayW;
          imgH = displayW / imgAspect;
          offsetX = 0;
          offsetY = (displayH - imgH) / 2;
        } else {
          imgH = displayH;
          imgW = displayH * imgAspect;
          offsetX = (displayW - imgW) / 2;
          offsetY = 0;
        }
        const clickX = touch.clientX - rect.left - offsetX;
        const clickY = touch.clientY - rect.top - offsetY;
        const x_pct = Math.max(0, Math.min(1, clickX / imgW));
        const y_pct = Math.max(0, Math.min(1, clickY / imgH));
        
        wsSend({ type: 'click', x_pct, y_pct, button: 'right' });
        if (navigator.vibrate) navigator.vibrate([30, 50, 30]);
        longPressTimer = null;
        setTimeout(refreshScreenshot, 500);
      }, 600);
    }
  }
}

function handleDesktopTouchEnd(event) {
  event.preventDefault();
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
  isPanning = false;
}

function handleDesktopTouchMove(event) {
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
  
  if (isPanning && event.touches.length === 1 && desktopZoom > 1.0) {
    event.preventDefault();
    const touch = event.touches[0];
    const deltaX = (touch.clientX - touchStartPos.x) / desktopZoom;
    const deltaY = (touch.clientY - touchStartPos.y) / desktopZoom;
    desktopPanX = panStartX + deltaX;
    desktopPanY = panStartY + deltaY;
    applyDesktopTransform();
  }
}

// Attach touch handlers to desktop image
window.addEventListener('load', () => {
  const img = document.getElementById('desktop-img');
  if (img) {
    img.addEventListener('touchstart', handleDesktopTouchStart, { passive: false });
    img.addEventListener('touchend', handleDesktopTouchEnd, { passive: false });
    img.addEventListener('touchmove', handleDesktopTouchMove, { passive: false });
  }
});

function sendTypeToDesktop() {
  const input = document.getElementById('desktop-type-input');
  const text = input.value;
  if (!text || !paired) return;
  input.value = '';
  wsSend({ type: 'type', data: text });
}

function sendKey(key) {
  if (!paired) return;
  wsSend({ type: 'key', data: key });
  setTimeout(refreshScreenshot, 400);
}

function sendScroll(direction, amount) {
  if (!paired) return;
  wsSend({ type: 'scroll', direction, amount });
  setTimeout(refreshScreenshot, 400);
}

// ── Tools ──────────────────────────────────────────────────────────────────
function sendDeviceInfo() {
  if (!paired) return;
  const info = getDeviceInfo();
  
  // Get battery info if available
  if ('getBattery' in navigator) {
    navigator.getBattery().then(battery => {
      info.battery = {
        level: Math.round(battery.level * 100),
        charging: battery.charging
      };
      const text = `📱 Device Info:\n` +
        `Device: ${info.device}\n` +
        `Screen: ${info.screen.width}x${info.screen.height} @ ${info.screen.pixelRatio}x\n` +
        `Orientation: ${info.screen.orientation}\n` +
        `Viewport: ${info.viewport.width}x${info.viewport.height}\n` +
        `Platform: ${info.platform}\n` +
        `Language: ${info.language}\n` +
        `Online: ${info.online}\n` +
        `Battery: ${info.battery.level}% ${info.battery.charging ? '(charging)' : ''}\n` +
        `Memory: ${info.memory} GB\n` +
        `CPU Cores: ${info.cores}\n` +
        `Touch Points: ${info.touchPoints}\n` +
        (info.connection ? `Connection: ${info.connection.effectiveType} (${info.connection.downlink} Mbps, ${info.connection.rtt}ms RTT)` : '');
      
      wsSend({ type: 'text', data: text });
      addChatMsg('user', text);
      switchTab('chat');
    }).catch(() => {
      const text = `📱 Device Info:\n` +
        `Device: ${info.device}\n` +
        `Screen: ${info.screen.width}x${info.screen.height}\n` +
        `Platform: ${info.platform}`;
      wsSend({ type: 'text', data: text });
      addChatMsg('user', text);
      switchTab('chat');
    });
  } else {
    const text = `📱 Device Info:\n` +
      `Device: ${info.device}\n` +
      `Screen: ${info.screen.width}x${info.screen.height}\n` +
      `Platform: ${info.platform}`;
    wsSend({ type: 'text', data: text });
    addChatMsg('user', text);
    switchTab('chat');
  }
}

function quickTool(tool, params) {
  if (!paired) return;
  document.getElementById('tool-result').textContent = 'Running…';
  wsSend({ type: 'tool', tool, params });
  if (navigator.vibrate) navigator.vibrate(20);
}

function sendCustomCmd() {
  const input = document.getElementById('custom-cmd');
  const text = input.value.trim();
  if (!text || !paired) return;
  input.value = '';
  addChatMsg('user', text);
  wsSend({ type: 'text', data: text });
  switchTab('chat');
}

// ── Files ──────────────────────────────────────────────────────────────────
function listFiles(path) {
  if (!paired) return;
  document.getElementById('files-list').innerHTML = '<p class="muted-text">Loading…</p>';
  wsSend({ type: 'tool', tool: 'file_controller', params: { action: 'list', path } });
  // Result comes back as tool_result — parse and render
  const origHandler = handleServerMessage;
  const oneShot = (msg) => {
    if (msg.type === 'tool_result') {
      renderFileList(msg.data, path);
    }
  };
  // We'll handle it in the main handler since tool_result is already handled
}

function renderFileList(text, basePath) {
  const container = document.getElementById('files-list');
  if (!text) { container.innerHTML = '<p class="muted-text">Empty</p>'; return; }
  const lines = text.split('\n').filter(l => l.trim());
  container.innerHTML = '';
  lines.forEach(line => {
    const item = document.createElement('div');
    item.className = 'file-item';
    const isDir = line.includes('[DIR]') || line.endsWith('/');
    item.innerHTML = `<span class="file-icon">${isDir ? '📁' : '📄'}</span>
                      <span class="file-name">${line.trim()}</span>`;
    container.appendChild(item);
  });
}

// ── Status ─────────────────────────────────────────────────────────────────
function setStatus(state, text) {
  const dot = document.getElementById('ws-status');
  const label = document.getElementById('status-text');
  dot.className = 'ws-dot ' + state;
  label.textContent = text;
}

// ── Auto-refresh desktop when active ───────────────────────────────────────
let autoRefreshInterval = null;

let autoRefreshEnabled = false;

function startAutoRefresh() {
  if (autoRefreshInterval) return;
  autoRefreshEnabled = true;
  autoRefreshInterval = setInterval(() => {
    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab && activeTab.id === 'tab-desktop' && paired && autoRefreshEnabled) {
      refreshScreenshot();
    }
  }, 3000); // Refresh every 3 seconds when desktop tab is active
}

function stopAutoRefresh() {
  autoRefreshEnabled = false;
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
  }
}

function toggleAutoRefresh() {
  if (autoRefreshEnabled) {
    stopAutoRefresh();
    addChatMsg('system', '🔄 Auto-refresh OFF');
  } else {
    startAutoRefresh();
    addChatMsg('system', '🔄 Auto-refresh ON (every 3s)');
  }
}

// Start auto-refresh when paired
window.addEventListener('load', () => {
  const observer = new MutationObserver(() => {
    if (paired) startAutoRefresh();
  });
  observer.observe(document.body, { childList: true, subtree: true });
});

// ── Ping keepalive ─────────────────────────────────────────────────────────
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    wsSend({ type: 'ping' });
  }
}, 25000);
