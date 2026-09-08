// xterm.js + WebSocket ↔ tmux bridge

let term = null;
let fitAddon = null;
let ws = null;
let reconnectTimer = null;

function initTerminal(sessionId) {
  const container = document.getElementById('term');
  if (!container) return;

  term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"SF Mono", "Cascadia Code", "Fira Code", Menlo, monospace',
    lineHeight: 1.2,
    scrollback: 5000,
    theme: {
      background:    '#010409',
      foreground:    '#e6edf3',
      cursor:        '#58a6ff',
      cursorAccent:  '#010409',
      black:         '#1b1f23',
      red:           '#f97583',
      green:         '#85e89d',
      yellow:        '#ffea7f',
      blue:          '#79b8ff',
      magenta:       '#b392f0',
      cyan:          '#39c5cf',
      white:         '#d1d5da',
      brightBlack:   '#585858',
      brightRed:     '#f97583',
      brightGreen:   '#85e89d',
      brightYellow:  '#ffea7f',
      brightBlue:    '#79b8ff',
      brightMagenta: '#b392f0',
      brightCyan:    '#39c5cf',
      brightWhite:   '#ffffff',
    },
  });

  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);

  const webLinksAddon = new WebLinksAddon.WebLinksAddon();
  term.loadAddon(webLinksAddon);

  term.open(container);
  fitAddon.fit();

  // Intercept touchpad/wheel scroll in capture phase so xterm.js never sees the event.
  // Without this, xterm forwards scroll as VT mouse sequences into Claude's chat input.
  // In xterm 5.x canvas mode, visual scroll is driven by .xterm-viewport scrollTop —
  // scrollLines() alone doesn't repaint, but scrollTop changes trigger xterm's scroll listener.
  container.addEventListener('wheel', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const viewport = container.querySelector('.xterm-viewport');
    if (!viewport) return;
    let px;
    if (e.deltaMode === 0) {        // pixel (Mac touchpad)
      px = e.deltaY;
    } else if (e.deltaMode === 1) { // line
      px = e.deltaY * 20;
    } else {                        // page
      px = e.deltaY * viewport.clientHeight;
    }
    viewport.scrollTop += px;
  }, { capture: true, passive: false });

  connectWebSocket(sessionId);

  // Resize handler
  const resizeObserver = new ResizeObserver(() => {
    if (fitAddon) {
      try { fitAddon.fit(); } catch (_) {}
    }
  });
  resizeObserver.observe(container);

  term.onResize(({ cols, rows }) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    }
  });

  // Keyboard input → WebSocket (filter mouse wheel sequences so they don't reach the pty)
  term.onData(data => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      // Drop VT mouse wheel sequences: SGR \x1b[<64;... or \x1b[<65;... and X10 \x1b[M@/A
      if (/^\x1b\[<6[45];/.test(data) || /^\x1b\[M[\x40\x41]/.test(data)) return;
      const bytes = new TextEncoder().encode(data);
      ws.send(bytes.buffer);
    }
  });
}

function connectWebSocket(sessionId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/sessions/${sessionId}`;

  ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    updateConnectionStatus('connected');
    clearTimeout(reconnectTimer);
    // Send initial terminal size
    if (term && fitAddon) {
      fitAddon.fit();
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    }
  };

  // Batch binary output through requestAnimationFrame so rapid bursts (e.g. Claude Code
  // streaming long responses) don't block the browser's main thread with individual writes.
  let _writeQueue = [];
  let _rafId = null;

  function _flushWrites() {
    _rafId = null;
    if (_writeQueue.length === 0) return;
    const chunks = _writeQueue.splice(0);
    let total = 0;
    for (const c of chunks) total += c.length;
    const combined = new Uint8Array(total);
    let off = 0;
    for (const c of chunks) { combined.set(c, off); off += c.length; }
    term.write(combined);
  }

  function _scheduleWrite(data) {
    _writeQueue.push(data);
    if (!_rafId) _rafId = requestAnimationFrame(_flushWrites);
  }

  ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      _scheduleWrite(new Uint8Array(event.data));
    } else if (typeof event.data === 'string') {
      term.write(event.data);
    }
  };

  ws.onclose = (event) => {
    updateConnectionStatus('disconnected');
    if (event.code !== 1008) {
      // Auto-reconnect after 3s (unless it was a policy close)
      reconnectTimer = setTimeout(() => connectWebSocket(sessionId), 3000);
    } else {
      term.write('\r\n\x1b[31m[Session ended or not found]\x1b[0m\r\n');
    }
  };

  ws.onerror = () => {
    updateConnectionStatus('error');
  };
}

function updateConnectionStatus(state) {
  const btn = document.getElementById('reconnectBtn');
  if (!btn) return;
  const labels = { connected: 'Connected', disconnected: 'Reconnect', error: 'Error — Reconnect' };
  btn.textContent = labels[state] || 'Reconnect';
  btn.style.color = state === 'connected' ? 'var(--green)' : '';
}

window.reconnectTerminal = function() {
  if (ws) { ws.close(); ws = null; }
  clearTimeout(reconnectTimer);
  const sessionId = window.SESSION_ID || location.pathname.split('/').pop();
  connectWebSocket(sessionId);
};
