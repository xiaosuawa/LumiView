"""
fastapi_demo.py — FastAPI inside LumiView via ASGI.

Shows:
  - A FastAPI app running on ``lumiview://`` (zero-config, no HTTP server)
  - REST endpoints + HTML template rendering
  - Using ``source=ASGI(fastapi_app)`` with ``Window.create``

No ``uvicorn``, no port, no ``pip install`` beyond ``lumiview`` + ``fastapi``.
The browser talks directly to FastAPI via the ``lumiview://`` custom protocol.

Run:
    pip install fastapi
    python examples/fastapi_demo.py
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from lumiview import App, Window, WindowOptions
from lumiview.serve import ASGI

# ── FastAPI app ─────────────────────────────────────────────────────────────

fastapi_app = FastAPI(title="LumiView + FastAPI")


@fastapi_app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    return """<!doctype html>
<html>
<head><meta charset="utf-8"><title>FastAPI + LumiView</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:2rem auto;">
  <h2>LumiView + FastAPI</h2>
  <p>This page is served by <strong>FastAPI</strong> running inside
     the <code>lumiview://</code> custom protocol — no HTTP server, no port.</p>

  <h3>GET /api/hello</h3>
  <button onclick="callHello()">Call /api/hello?name=FastAPI</button>
  <pre id="hello-result"></pre>

  <h3>POST /api/echo</h3>
  <textarea id="echo-input" rows="3" style="width:100%">{"msg":"hello"}</textarea>
  <br><button onclick="callEcho()">POST /api/echo</button>
  <pre id="echo-result"></pre>

<script>
  async function callHello() {
    const r = await fetch('/api/hello?name=FastAPI');
    document.getElementById('hello-result').textContent = JSON.stringify(await r.json(), null, 2);
  }
  async function callEcho() {
    const body = document.getElementById('echo-input').value;
    const r = await fetch('/api/echo', { method:'POST', body });
    document.getElementById('echo-result').textContent = JSON.stringify(await r.json(), null, 2);
  }
</script>
</body>
</html>"""


@fastapi_app.get("/api/hello")
async def hello(name: str = "World"):
    """A simple JSON endpoint."""
    return {"greeting": f"Hello, {name}!"}


@fastapi_app.post("/api/echo")
async def echo(request: Request):
    """Echo the raw request body back, with metadata."""
    body = await request.body()
    return {
        "method": request.method,
        "path": request.url.path,
        "body": body.decode(),
        "client_host": request.client.host if request.client else "unknown",
    }


# ── LumiView app ───────────────────────────────────────────────────────────

app = App(name="ASGIDemo")


async def main():
    await Window.create(WindowOptions(
        title="FastAPI + LumiView",
        source=ASGI(fastapi_app),
        width=760,
        height=600,
        devtools=True,
    ))
    print("FastAPI app running at lumiview://app/")
    print("Open DevTools → Network tab to see requests flowing through the custom protocol.")


if __name__ == "__main__":
    app.run(main)
