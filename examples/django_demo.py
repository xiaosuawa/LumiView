"""
django_demo.py — Django inside LumiView via WSGI.

Shows:
  - A Django app running on ``lumiview://`` (zero-config, no HTTP server)
  - URL routing + view functions + the Django template engine
  - HTML form POST handling and JSON API endpoints
  - Using ``source=WSGI(django_app)`` with ``Window.create``

No ``runserver``, no port, no ``pip install`` beyond ``lumiview`` + ``django``.
The browser talks directly to Django via the ``lumiview://`` custom protocol.

Run:
    pip install django
    python examples/django_demo.py
"""

import json
import platform

from django import get_version
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.http import HttpResponse, JsonResponse
from django.template import Context, Template
from django.urls import path

from lumiview import App, Window, WindowOptions
from lumiview.serve import WSGI

# ── Django app (single-file, no settings.py / urls.py needed) ──────────────

settings.configure(
    DEBUG=True,
    SECRET_KEY="lumiview-django-demo",
    ALLOWED_HOSTS=["lumiview"],
    ROOT_URLCONF=__name__,
    INSTALLED_APPS=[],
    # CsrfViewMiddleware is omitted on purpose: the lumiview:// protocol is
    # not reachable from external browsers, so the cross-site attack surface
    # is closed by design. Keep it if you load remote content into the WebView.
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.middleware.common.CommonMiddleware",
    ],
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    USE_TZ=True,
    LANGUAGE_CODE="zh-hans",
)
django.setup()

INDEX_TEMPLATE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Django + LumiView</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:2rem auto;">
  <h2>LumiView + Django</h2>
  <p>This page is rendered by the <strong>Django template engine</strong> and served
     through the <code>lumiview://</code> custom protocol — no runserver, no port.
     Django version <strong>{{ django_version }}</strong> on Python {{ python_version }}.</p>

  <h3>POST form</h3>
  <form method="post" action="/">
    <input name="message" placeholder="Type a message…" style="width:70%">
    <button type="submit">Submit</button>
  </form>
  {% if last_message %}<p><strong>Last message:</strong> {{ last_message }}</p>{% endif %}

  <h3>GET /api/info</h3>
  <button onclick="callInfo()">Load framework info</button>
  <pre id="info-result"></pre>

  <h3>POST /api/echo</h3>
  <textarea id="echo-input" rows="3" style="width:100%">{"msg":"hello django"}</textarea>
  <br><button onclick="callEcho()">POST /api/echo</button>
  <pre id="echo-result"></pre>

<script>
  async function callInfo() {
    const r = await fetch('/api/info');
    document.getElementById('info-result').textContent = JSON.stringify(await r.json(), null, 2);
  }
  async function callEcho() {
    const body = document.getElementById('echo-input').value;
    const r = await fetch('/api/echo', { method: 'POST', body });
    document.getElementById('echo-result').textContent = JSON.stringify(await r.json(), null, 2);
  }
</script>
</body>
</html>"""


def index(request):
    """Render the main page; accept form POSTs."""
    last_message = ""
    if request.method == "POST":
        last_message = request.POST.get("message", "")
    html = Template(INDEX_TEMPLATE).render(Context({
        "django_version": get_version(),
        "python_version": platform.python_version(),
        "last_message": last_message,
    }))
    return HttpResponse(html)


def api_info(request):
    """A simple JSON endpoint — note the ``lumiview://`` scheme."""
    return JsonResponse({
        "framework": "Django",
        "django_version": get_version(),
        "python_version": platform.python_version(),
        "protocol": request.scheme,
    })


def api_echo(request):
    """Echo a JSON body back, with request metadata."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    return JsonResponse({
        "method": request.method,
        "path": request.path,
        "received": data,
        "echo": data.get("msg", ""),
    })


# URLconf lives in this module too (ROOT_URLCONF = __name__).
urlpatterns = [
    path("", index),
    path("api/info", api_info),
    path("api/echo", api_echo),
]

# A standard Django WSGI application — fully compatible with the WSGI adapter.
django_app = get_wsgi_application()

# ── LumiView app ───────────────────────────────────────────────────────────

app = App(name="DjangoDemo")


async def main():
    await Window.create(WindowOptions(
        title="Django + LumiView",
        source=WSGI(django_app),
        width=760,
        height=640,
        devtools=True,
    ))
    print("Django app running at lumiview://app/")
    print("Open DevTools → Network tab to see requests flowing through the custom protocol.")


if __name__ == "__main__":
    app.run(main)
