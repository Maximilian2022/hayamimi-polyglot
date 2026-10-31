"""
Hayamimi For Business - Local Web Server for Browser View & Screen Sharing.
Security:
  - Strictly bound to 127.0.0.1 (Loopback). Zero access from LAN / external networks.
  - Strict Host & Origin check (Localhost only, blocks DNS rebinding).
  - DOM XSS protection (escaped text rendering).
  - Pure in-memory event stream. Zero transcript saved to disk.
"""

from __future__ import annotations

import asyncio
import html
import json
import threading
from typing import AsyncGenerator, Dict, List, Optional, Set

from fastapi import FastAPI, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import uvicorn


app = FastAPI(title="Hayamimi Polyglot View", docs_url=None, redoc_url=None, openapi_url=None)

@app.on_event("startup")
async def on_startup():
    """Register running event loop for thread-safe event queuing."""
    set_server_loop(asyncio.get_running_loop())

# 1. DNS Rebinding Protection: Strict Host whitelist
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "127.0.0.1:8844", "localhost:8844"],
)

# Active SSE listener queues & server event loop
_loop: Optional[asyncio.AbstractEventLoop] = None
_subscribers: Set[asyncio.Queue] = set()
_transcript_history: List[Dict[str, str]] = []  # In-memory only (max 100 items)
_lock = threading.Lock()


def set_server_loop(loop: asyncio.AbstractEventLoop):
    """Register server event loop for thread-safe cross-thread event delivery."""
    global _loop
    _loop = loop


def broadcast_event(event_type: str, data: dict):
    """Thread-safe broadcast to all active SSE browser connections."""
    with _lock:
        if event_type == "subtitle":
            _transcript_history.append(dict(data))
            if len(_transcript_history) > 100:
                _transcript_history.pop(0)
        elif event_type == "translation":
            # Update matching item in history so reconnecting clients get finalized translations
            target_id = data.get("id")
            if target_id:
                for item in reversed(_transcript_history):
                    if item.get("id") == target_id:
                        item.setdefault("translations", {}).update(data.get("translations", {}))
                        break
            elif _transcript_history:
                _transcript_history[-1].setdefault("translations", {}).update(data.get("translations", {}))

        message = json.dumps({"event": event_type, "data": data}, ensure_ascii=False)
        for q in list(_subscribers):
            try:
                if _loop and _loop.is_running():
                    _loop.call_soon_threadsafe(q.put_nowait, message)
                else:
                    q.put_nowait(message)
            except Exception:
                pass


def clear_history():
    """Clear memory transcript."""
    with _lock:
        _transcript_history.clear()


def _is_local_request(request: Request) -> bool:
    """
    Verify request originates from local loopback with strict Host and Origin validation.
    Prevents cross-site attacks, external access, and DNS rebinding.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "localhost", "::1"):
        return False

    # Check Host header
    host_header = request.headers.get("host", "").lower()
    if host_header not in ("127.0.0.1:8844", "localhost:8844", "127.0.0.1", "localhost"):
        return False

    # Check Origin / Sec-Fetch-Site (if present)
    origin = request.headers.get("origin")
    if origin and origin not in ("http://127.0.0.1:8844", "http://localhost:8844"):
        return False

    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site and sec_fetch_site not in ("same-origin", "none"):
        return False

    return True


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Inject strict security headers into all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'; frame-ancestors 'none';"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint strictly for local browser."""
    if not _is_local_request(request):
        return HTMLResponse(status_code=403, content="Forbidden: Localhost only")

    # Queue with backpressure limit
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(q)

    # Snapshot history inside lock, then yield outside lock (thread-safe, no lock contention)
    with _lock:
        history_snapshot = list(_transcript_history)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Send initial history without blocking the lock
            for item in history_snapshot:
                msg = json.dumps({"event": "subtitle", "data": item}, ensure_ascii=False)
                yield f"data: {msg}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keep-alive ping
                    yield ": ping\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/view", response_class=HTMLResponse)
async def browser_view(request: Request):
    """Clean, high-contrast browser view suitable for Zoom screen sharing."""
    if not _is_local_request(request):
        return HTMLResponse(status_code=403, content="Forbidden: Localhost only")

    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>Hayamimi Polyglot - リアルタイム多言語同時並行通訳</title>
  <style>
    :root {
      --bg: #0F172A;
      --card-bg: #1E293B;
      --border: #334155;
      --self-tag: #38BDF8;
      --remote-tag: #A78BFA;
      --text: #F8FAFC;
      --trans: #FBBF24;
    }
    body {
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 20px;
    }
    .title {
      font-size: 20px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .badge {
      font-size: 12px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.2);
      color: #34D399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }
    .actions button {
      background: #3B82F6;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
    }
    .actions button:hover { background: #2563EB; }
    .feed {
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-width: 1000px;
      margin: 0 auto;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      animation: fadeIn 0.2s ease-out;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .speaker-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .tag {
      font-size: 12px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 4px;
    }
    .tag.self { background: rgba(56, 189, 248, 0.15); color: var(--self-tag); }
    .tag.remote { background: rgba(167, 139, 250, 0.15); color: var(--remote-tag); }
    .time { font-size: 12px; color: #64748B; }
    .original { font-size: 16px; line-height: 1.5; color: var(--text); }
    .translation {
      font-size: 15px;
      line-height: 1.5;
      color: var(--trans);
      padding-top: 4px;
      border-top: 1px dashed var(--border);
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <span>🎙️🌐 Hayamimi Polyglot</span>
      <span class="badge">● リアルタイム会議接続中 (127.0.0.1)</span>
    </div>
    <div class="actions">
      <button onclick="copyAllText()">📋 全議事録テキストをコピー</button>
      <button onclick="clearDisplay()" style="background: #475569; margin-left: 8px;">🗑️ クリア</button>
    </div>
  </div>

  <div class="feed" id="feed">
    <div class="card" id="emptyNotice">
      <div style="color: #94A3B8; text-align: center; padding: 20px;">
        発言が検出されると、ここにリアルタイムに文字起こしと翻訳が表示されます。<br>
        この画面をそのまま Zoom や Teams の画面共有で共有できます。
      </div>
    </div>
  </div>

  <script>
    const feed = document.getElementById('feed');
    const emptyNotice = document.getElementById('emptyNotice');
    let allLines = [];

    // Safe HTML escape helper (XSS prevention)
    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    const evtSource = new EventSource('/events');
    evtSource.onmessage = function(e) {
      try {
        const payload = JSON.parse(e.data);
        if (payload.event === 'subtitle') {
          appendSubtitle(payload.data);
        } else if (payload.event === 'translation') {
          updateTranslation(payload.data);
        }
      } catch (err) {}
    };

    function appendSubtitle(data) {
      if (emptyNotice) emptyNotice.style.display = 'none';

      const cardId = 'card-' + (data.id || Math.random().toString(36).substring(2, 9));
      // Avoid duplicate cards
      let card = document.getElementById(cardId);
      if (card) {
        if (data.translations) {
          updateTranslation(data);
        }
        return;
      }

      card = document.createElement('div');
      card.className = 'card';
      card.id = cardId;

      const isSelf = data.track === 'self';
      const tagClass = isSelf ? 'self' : 'remote';
      const tagText = isSelf ? '自分' : '相手';
      const now = new Date().toLocaleTimeString();

      const safeText = escapeHtml(data.text);
      card.innerHTML = `
        <div class="speaker-row">
          <span class="tag ${tagClass}">[${tagText}]</span>
          <span class="time">${now}</span>
        </div>
        <div class="original">${safeText}</div>
        <div class="trans-container"></div>
      `;

      feed.appendChild(card);
      if (data.translations) {
        updateTranslation(data);
      }
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    }

    function updateTranslation(data) {
      const cardId = 'card-' + data.id;
      const card = document.getElementById(cardId) || feed.lastElementChild;
      if (!card) return;

      const container = card.querySelector('.trans-container');
      if (!container) return;

      let transHtml = '';
      if (data.translations && typeof data.translations === 'object') {
        for (const [lang, transText] of Object.entries(data.translations)) {
          if (transText) {
            transHtml += `<div class="translation">↳ <b style="color:#38BDF8;">[${lang.toUpperCase()}]</b> ${escapeHtml(transText)}</div>`;
          }
        }
      } else if (data.translation) {
        transHtml = `<div class="translation">↳ ${escapeHtml(data.translation)}</div>`;
      }
      container.innerHTML = transHtml;
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    }

    function copyAllText() {
      if (allLines.length === 0) {
        alert('コピーできるテキストがありません。');
        return;
      }
      navigator.clipboard.writeText(allLines.join('\\n\\n')).then(() => {
        alert('クリップボードにコピーしました！');
      });
    }

    function clearDisplay() {
      feed.innerHTML = '';
      allLines = [];
    }
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


class BusinessWebServer:
    """Controls the background uvicorn server thread on 127.0.0.1:8844."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8844):
        self.host = host
        self.port = port
        self.server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self.server.run, name="WebServerThread", daemon=True)
        self._thread.start()

    def stop(self):
        if self.server:
            self.server.should_exit = True
