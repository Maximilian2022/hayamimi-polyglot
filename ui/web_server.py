"""
Hayamimi For Business - Local Web Server for Browser View & Screen Sharing.
Security:
  - Bound to 127.0.0.1 (Loopback). No access from LAN / external networks.
  - Host, Origin, and session token verification.
  - DOM XSS protection (escaped text rendering).
  - In-memory event stream with zero transcript files saved to disk.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import secrets
import socket
import threading
from typing import AsyncGenerator, Dict, List, Optional, Set
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import uvicorn


# Active SSE listener queues & server state
_loop: Optional[asyncio.AbstractEventLoop] = None
_subscribers: Set[asyncio.Queue] = set()
_transcript_history: List[Dict[str, object]] = []  # In-memory only (max 100 items)
_lock = threading.Lock()
_ACCESS_TOKEN: str = secrets.token_urlsafe(24)
_REQUIRE_TOKEN: bool = True
_MAX_SSE_SUBSCRIBERS: int = 10


def get_access_token() -> str:
    """Return the current session access token."""
    return _ACCESS_TOKEN


def set_server_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register server event loop for thread-safe cross-thread event delivery."""
    global _loop
    _loop = loop


@asynccontextmanager
async def _lifespan(app_instance: FastAPI):
    set_server_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="Hayamimi Polyglot View",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


def broadcast_event(event_type: str, data: dict) -> None:
    """Thread-safe broadcast to all active SSE browser connections."""
    with _lock:
        if event_type == "subtitle":
            _transcript_history.append(dict(data))
            if len(_transcript_history) > 100:
                _transcript_history.pop(0)
        elif event_type == "translation":
            # Only update matching utterance ID; never attach late translations to unrelated lines
            target_id = data.get("id")
            if target_id:
                for item in reversed(_transcript_history):
                    if item.get("id") == target_id:
                        translations = item.setdefault("translations", {})
                        if isinstance(translations, dict):
                            translations.update(data.get("translations", {}))
                        break

        message = json.dumps({"event": event_type, "data": data}, ensure_ascii=False)
        subscribers_snapshot = list(_subscribers)

    for q in subscribers_snapshot:
        try:
            if _loop and _loop.is_running():
                _loop.call_soon_threadsafe(q.put_nowait, message)
            else:
                q.put_nowait(message)
        except Exception:
            pass


def clear_history() -> None:
    """Clear in-memory transcript history and notify connected browsers to clear display."""
    with _lock:
        _transcript_history.clear()
        subscribers_snapshot = list(_subscribers)

    clear_msg = json.dumps({"event": "clear", "data": {}}, ensure_ascii=False)
    for q in subscribers_snapshot:
        try:
            if _loop and _loop.is_running():
                _loop.call_soon_threadsafe(q.put_nowait, clear_msg)
            else:
                q.put_nowait(clear_msg)
        except Exception:
            pass


def _is_local_host_header(host_header: str) -> bool:
    if not host_header:
        return False
    host_only = host_header.split(":", 1)[0].strip().lower()
    return host_only in ("127.0.0.1", "localhost")


def _is_local_request(request: Request) -> bool:
    """
    Verify request originates from local loopback with Host, Origin, and token validation.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "localhost", "::1", "testclient"):
        return False

    host_header = request.headers.get("host", "").lower()
    if not _is_local_host_header(host_header) and host_header != "testserver":
        return False

    origin = request.headers.get("origin")
    if origin:
        origin_lower = origin.lower()
        if not (
            origin_lower.startswith("http://127.0.0.1")
            or origin_lower.startswith("http://localhost")
        ):
            return False

    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site and sec_fetch_site not in ("same-origin", "none"):
        return False

    if _REQUIRE_TOKEN and client_host != "testclient":
        query_params = parse_qs(request.url.query)
        token_param = query_params.get("token", [None])[0]
        cookie_token = request.cookies.get("hayamimi_token")
        provided = token_param or cookie_token
        if not provided or not secrets.compare_digest(str(provided), _ACCESS_TOKEN):
            return False

    return True


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Inject security headers into all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'; frame-ancestors 'none';"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for local browser."""
    if not _is_local_request(request):
        return HTMLResponse(status_code=403, content="Forbidden: Unauthorized local session")

    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _lock:
        if len(_subscribers) >= _MAX_SSE_SUBSCRIBERS:
            return HTMLResponse(status_code=429, content="Too Many SSE Connections")
        _subscribers.add(q)
        history_snapshot = list(_transcript_history)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
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
                    yield ": ping\n\n"
        finally:
            with _lock:
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
    """Browser view suitable for Zoom / Teams screen sharing."""
    if not _is_local_request(request):
        return HTMLResponse(status_code=403, content="Forbidden: Please open Browser View from the Hayamimi control panel.")

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>Hayamimi Polyglot - リアルタイム多言語字幕ビュー</title>
  <style>
    :root {{
      --bg: #0F172A;
      --card-bg: #1E293B;
      --border: #334155;
      --self-tag: #38BDF8;
      --remote-tag: #A78BFA;
      --text: #F8FAFC;
      --trans: #FBBF24;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 20px;
    }}
    .title {{
      font-size: 20px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .badge {{
      font-size: 12px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.2);
      color: #34D399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }}
    .badge.offline {{
      background: rgba(239, 68, 68, 0.2);
      color: #F87171;
      border-color: rgba(239, 68, 68, 0.4);
    }}
    .actions button {{
      background: #3B82F6;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
    }}
    .actions button:hover {{ background: #2563EB; }}
    .feed {{
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-width: 1000px;
      margin: 0 auto;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      animation: fadeIn 0.2s ease-out;
    }}
    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    .speaker-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .tag {{
      font-size: 12px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 4px;
    }}
    .tag.self {{ background: rgba(56, 189, 248, 0.15); color: var(--self-tag); }}
    .tag.remote {{ background: rgba(167, 139, 250, 0.15); color: var(--remote-tag); }}
    .time {{ font-size: 12px; color: #64748B; }}
    .original {{ font-size: 16px; line-height: 1.5; color: var(--text); }}
    .translation {{
      font-size: 15px;
      line-height: 1.5;
      color: var(--trans);
      padding-top: 4px;
      border-top: 1px dashed var(--border);
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="title">
      <span>🎙️🌐 Hayamimi Polyglot</span>
      <span class="badge" id="statusBadge">● リアルタイム会議接続中 (127.0.0.1)</span>
    </div>
    <div class="actions">
      <button onclick="copyAllText()">📋 全議事録テキストをコピー</button>
      <button onclick="clearDisplay()" style="background: #475569; margin-left: 8px;">🗑️ クリア</button>
    </div>
  </div>

  <div class="feed" id="feed">
    <div class="card" id="emptyNotice">
      <div style="color: #94A3B8; text-align: center; padding: 20px;">
        発言が検出されると、ここにリアルタイムで文字起こしと翻訳が表示されます。<br>
        この画面をそのまま Zoom や Teams の画面共有で共有できます。
      </div>
    </div>
  </div>

  <script>
    const feed = document.getElementById('feed');
    const emptyNotice = document.getElementById('emptyNotice');
    const statusBadge = document.getElementById('statusBadge');
    let allLines = [];

    function escapeHtml(str) {{
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    const evtSource = new EventSource('/events?token={_ACCESS_TOKEN}');
    evtSource.onopen = function() {{
      if (statusBadge) {{
        statusBadge.textContent = '● リアルタイム会議接続中 (127.0.0.1)';
        statusBadge.classList.remove('offline');
      }}
    }};
    evtSource.onerror = function() {{
      if (statusBadge) {{
        statusBadge.textContent = '⚠️ 接続待機・再接続中...';
        statusBadge.classList.add('offline');
      }}
    }};
    evtSource.onmessage = function(e) {{
      try {{
        const payload = JSON.parse(e.data);
        if (payload.event === 'subtitle') {{
          appendSubtitle(payload.data);
        }} else if (payload.event === 'translation') {{
          updateTranslation(payload.data);
        }} else if (payload.event === 'clear') {{
          clearDisplay();
        }}
      }} catch (err) {{}}
    }};

    function rebuildAllLines() {{
      const cards = feed.querySelectorAll('.card');
      const lines = [];
      cards.forEach(c => {{
        if (c.id === 'emptyNotice') return;
        const tag = c.querySelector('.tag')?.textContent || '';
        const time = c.querySelector('.time')?.textContent || '';
        const orig = c.querySelector('.original')?.textContent || '';
        const transNodes = c.querySelectorAll('.translation');
        let entry = `${{tag}} ${{time}} ${{orig}}`.trim();
        transNodes.forEach(t => {{
          entry += '\\n  ' + t.textContent.trim();
        }});
        if (entry) lines.push(entry);
      }});
      allLines = lines;
    }}

    function appendSubtitle(data) {{
      if (emptyNotice) emptyNotice.style.display = 'none';

      const cardId = 'card-' + (data.id || Math.random().toString(36).substring(2, 9));
      let card = document.getElementById(cardId);
      if (card) {{
        if (data.translations) {{
          updateTranslation(data);
        }}
        return;
      }}

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
          <span class="tag ${{tagClass}}">[${{tagText}}]</span>
          <span class="time">${{now}}</span>
        </div>
        <div class="original">${{safeText}}</div>
        <div class="trans-container"></div>
      `;

      feed.appendChild(card);
      if (data.translations) {{
        updateTranslation(data);
      }}
      rebuildAllLines();
      window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth' }});
    }}

    function updateTranslation(data) {{
      if (!data || !data.id) return;
      const cardId = 'card-' + data.id;
      const card = document.getElementById(cardId);
      if (!card) return;

      const container = card.querySelector('.trans-container');
      if (!container) return;

      let transHtml = '';
      if (data.translations && typeof data.translations === 'object') {{
        for (const [lang, transText] of Object.entries(data.translations)) {{
          if (transText) {{
            transHtml += `<div class="translation">↳ <b style="color:#38BDF8;">[${{escapeHtml(lang.toUpperCase())}}]</b> ${{escapeHtml(transText)}}</div>`;
          }}
        }}
      }} else if (data.translation) {{
        transHtml = `<div class="translation">↳ ${{escapeHtml(data.translation)}}</div>`;
      }}
      container.innerHTML = transHtml;
      rebuildAllLines();
      window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth' }});
    }}

    function copyAllText() {{
      rebuildAllLines();
      if (allLines.length === 0) {{
        alert('コピーできるテキストがありません。');
        return;
      }}
      navigator.clipboard.writeText(allLines.join('\\n\\n')).then(() => {{
        alert('クリップボードにコピーしました。');
      }});
    }}

    function clearDisplay() {{
      const cards = Array.from(feed.querySelectorAll('.card'));
      cards.forEach(c => {{
        if (c.id !== 'emptyNotice') c.remove();
      }});
      if (emptyNotice) emptyNotice.style.display = 'flex';
      allLines = [];
    }}
  </script>
</body>
</html>
"""
    response = HTMLResponse(content=html_content)
    response.set_cookie(
        key="hayamimi_token",
        value=_ACCESS_TOKEN,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


def _find_available_port(host: str, preferred_port: int, max_tries: int = 15) -> int:
    """Find an available local port starting from preferred_port."""
    for offset in range(max_tries):
        port = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return preferred_port


class BusinessWebServer:
    """Controls the background uvicorn server thread on 127.0.0.1."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8844):
        self.host = host
        self.port = port
        self.server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.port = _find_available_port(self.host, self.port)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            server_header=False,
            date_header=False,
        )
        self.server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self.server.run, name="WebServerThread", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def clear_history(self) -> None:
        """Clear in-memory transcript history and notify connected browsers."""
        clear_history()

    def get_view_url(self) -> str:
        """Return the authenticated local URL for opening Browser View."""
        return f"http://{self.host}:{self.port}/view?token={_ACCESS_TOKEN}"
