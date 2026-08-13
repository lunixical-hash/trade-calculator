"""
Roblox account login server for Lunix's AI Trade Assistant.

Handles OAuth 2.0 (authorization code + PKCE) and username lookup so the
static GitHub Pages calculator can show a connected Roblox identity.

Setup:
  1. Create an OAuth 2.0 app at https://create.roblox.com/dashboard/credentials
     - Redirect URI: http://127.0.0.1:8787/auth/callback  (local)
       and/or https://YOUR-AUTH-HOST/auth/callback         (hosted)
     - Scopes: openid, profile
  2. Copy .env.example → .env and fill ROBLOX_CLIENT_ID / ROBLOX_CLIENT_SECRET
  3. Set PUBLIC_APP_URL to your calculator origin
     (e.g. https://lunixical-hash.github.io/trade-calculator)
  4. python auth_server.py
  5. Put the auth server origin in auth_public.json → authApiBase

Endpoints:
  GET  /health
  GET  /auth/login
  GET  /auth/callback
  GET  /api/me
  POST /api/logout
  POST /api/resolve-user   JSON {{"username":"..."}}
  GET  /api/config         Public flags for the frontend
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

AUTHORIZE_URL = "https://apis.roblox.com/oauth/v1/authorize"
TOKEN_URL = "https://apis.roblox.com/oauth/v1/token"
USERINFO_URL = "https://apis.roblox.com/oauth/v1/userinfo"
USERS_API = "https://users.roblox.com/v1/usernames/users"
USERS_BY_ID = "https://users.roblox.com/v1/users/{}"
THUMB_API = (
    "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    "?userIds={}&size=150x150&format=Png&isCircular=false"
)

# In-memory stores (fine for a single small server process)
_pending: dict[str, dict[str, Any]] = {}
_sessions: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_cached_cfg: dict[str, str] | None = None

SESSION_TTL_SEC = 60 * 60 * 24 * 30  # 30 days
PENDING_TTL_SEC = 60 * 10


def load_dotenv(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def cfg() -> dict[str, str]:
    global _cached_cfg
    if _cached_cfg is not None:
        return _cached_cfg
    host = env("AUTH_HOST", "127.0.0.1")
    port = env("AUTH_PORT", "8787")
    public_auth = env("AUTH_PUBLIC_URL", f"http://{host}:{port}").rstrip("/")
    _cached_cfg = {
        "host": host,
        "port": port,
        "auth_public_url": public_auth,
        "client_id": env("ROBLOX_CLIENT_ID"),
        "client_secret": env("ROBLOX_CLIENT_SECRET"),
        "redirect_uri": env(
            "ROBLOX_REDIRECT_URI", f"{public_auth}/auth/callback"
        ),
        "app_url": env(
            "PUBLIC_APP_URL",
            "https://lunixical-hash.github.io/trade-calculator/trade_calculator.html",
        ),
        "session_secret": env("SESSION_SECRET") or secrets.token_hex(32),
        "cors_origins": env(
            "CORS_ORIGINS",
            "http://127.0.0.1:5500,http://localhost:5500,"
            "https://lunixical-hash.github.io,null",
        ),
    }
    return _cached_cfg


def reload_cfg() -> dict[str, str]:
    """Clear cached config (tests / after editing env)."""
    global _cached_cfg
    _cached_cfg = None
    return cfg()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(32))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def http_json(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    form: dict | None = None,
) -> Any:
    hdrs = {
        "User-Agent": "LunixTradeAssistantAuth/1.0",
        "Accept": "application/json",
    }
    if headers:
        hdrs.update(headers)
    body: bytes | None = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {err_body[:500]}") from e


def avatar_for(user_id: int | str) -> str | None:
    try:
        data = http_json("GET", THUMB_API.format(user_id))
        rows = (data or {}).get("data") or []
        if rows and rows[0].get("imageUrl"):
            return str(rows[0]["imageUrl"])
    except Exception:
        pass
    return (
        "https://www.roblox.com/headshot-thumbnail/image"
        f"?userId={user_id}&width=150&height=150&format=png"
    )


def resolve_username(username: str) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    if not username or len(username) > 20:
        raise ValueError("Enter a valid Roblox username")
    data = http_json(
        "POST",
        USERS_API,
        data={"usernames": [username], "excludeBannedUsers": True},
    )
    rows = (data or {}).get("data") or []
    if not rows:
        raise ValueError(f"No Roblox user named “{username}”")
    row = rows[0]
    user_id = int(row["id"])
    # Prefer canonical casing from users API
    name = str(row.get("name") or username)
    display = str(row.get("displayName") or name)
    return {
        "id": user_id,
        "username": name,
        "displayName": display,
        "profile": f"https://www.roblox.com/users/{user_id}/profile",
        "picture": avatar_for(user_id),
        "authMethod": "username",
    }


def user_from_oauth(access_token: str) -> dict[str, Any]:
    info = http_json(
        "GET",
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not isinstance(info, dict) or not info.get("sub"):
        raise RuntimeError("userinfo missing sub")
    user_id = str(info["sub"])
    username = str(
        info.get("preferred_username")
        or info.get("nickname")
        or info.get("name")
        or user_id
    )
    display = str(info.get("name") or info.get("nickname") or username)
    picture = info.get("picture") or avatar_for(user_id)
    return {
        "id": int(user_id) if user_id.isdigit() else user_id,
        "username": username,
        "displayName": display,
        "profile": info.get("profile")
        or f"https://www.roblox.com/users/{user_id}/profile",
        "picture": picture,
        "authMethod": "oauth",
    }


def sign_session(session_id: str, secret: str) -> str:
    sig = hmac.new(
        secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:24]
    return f"{session_id}.{sig}"


def verify_session_token(token: str, secret: str) -> str | None:
    if not token or "." not in token:
        return None
    session_id, _, sig = token.partition(".")
    expect = hmac.new(
        secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:24]
    if not hmac.compare_digest(sig, expect):
        return None
    return session_id


def purge_expired() -> None:
    now = time.time()
    with _lock:
        for store, ttl in ((_pending, PENDING_TTL_SEC), (_sessions, SESSION_TTL_SEC)):
            dead = [k for k, v in store.items() if now - v.get("created", 0) > ttl]
            for k in dead:
                store.pop(k, None)


def create_session(user: dict[str, Any], c: dict[str, str]) -> str:
    purge_expired()
    session_id = secrets.token_urlsafe(24)
    with _lock:
        _sessions[session_id] = {"created": time.time(), "user": user}
    return sign_session(session_id, c["session_secret"])


def get_session_user(token: str, c: dict[str, str]) -> dict[str, Any] | None:
    purge_expired()
    session_id = verify_session_token(token, c["session_secret"])
    if not session_id:
        return None
    with _lock:
        row = _sessions.get(session_id)
    if not row:
        return None
    return row.get("user")


def drop_session(token: str, c: dict[str, str]) -> None:
    session_id = verify_session_token(token, c["session_secret"])
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


class Handler(BaseHTTPRequestHandler):
    server_version = "LunixAuth/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[auth] {self.address_string()} {fmt % args}")

    def _cors_origin(self) -> str | None:
        c = cfg()
        origin = self.headers.get("Origin")
        allowed = {o.strip() for o in c["cors_origins"].split(",") if o.strip()}
        if origin and (origin in allowed or "*" in allowed):
            return origin
        # file:// opens often send Origin: null
        if origin == "null" and "null" in allowed:
            return "null"
        return None

    def _send(
        self,
        code: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"))

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _bearer(self) -> str | None:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        # Also accept query token for redirect landing
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        vals = qs.get("token") or qs.get("session")
        return vals[0] if vals else None

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self._cors_origin() or "*"
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        c = cfg()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            self._json(200, {"ok": True})
            return

        if path == "/api/config":
            self._json(
                200,
                {
                    "oauthReady": bool(c["client_id"] and c["client_secret"]),
                    "usernameLink": True,
                    "appUrl": c["app_url"],
                },
            )
            return

        if path == "/api/me":
            token = self._bearer()
            user = get_session_user(token or "", c) if token else None
            if not user:
                self._json(401, {"error": "Not signed in"})
                return
            self._json(200, {"user": user})
            return

        if path == "/auth/login":
            if not c["client_id"] or not c["client_secret"]:
                self._json(
                    503,
                    {
                        "error": "OAuth is not configured. Set ROBLOX_CLIENT_ID and "
                        "ROBLOX_CLIENT_SECRET in .env (see .env.example)."
                    },
                )
                return
            verifier, challenge = pkce_pair()
            state = secrets.token_urlsafe(24)
            with _lock:
                _pending[state] = {
                    "created": time.time(),
                    "verifier": verifier,
                }
            qs = urllib.parse.urlencode(
                {
                    "client_id": c["client_id"],
                    "redirect_uri": c["redirect_uri"],
                    "scope": "openid profile",
                    "response_type": "code",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
            loc = f"{AUTHORIZE_URL}?{qs}"
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
            return

        if path == "/auth/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            err = (qs.get("error") or [None])[0]
            if err:
                desc = (qs.get("error_description") or [err])[0]
                self._redirect_app(c, error=str(desc))
                return
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            if not code or not state:
                self._redirect_app(c, error="Missing OAuth code/state")
                return
            with _lock:
                pending = _pending.pop(state, None)
            if not pending:
                self._redirect_app(c, error="Login expired — try again")
                return
            try:
                token_payload = http_json(
                    "POST",
                    TOKEN_URL,
                    form={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": c["redirect_uri"],
                        "client_id": c["client_id"],
                        "client_secret": c["client_secret"],
                        "code_verifier": pending["verifier"],
                    },
                )
                access = (token_payload or {}).get("access_token")
                if not access:
                    raise RuntimeError("No access_token in token response")
                user = user_from_oauth(str(access))
                session = create_session(user, c)
                self._redirect_app(c, token=session)
            except Exception as e:
                self._redirect_app(c, error=str(e))
            return

        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        c = cfg()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/logout":
            token = self._bearer()
            if token:
                drop_session(token, c)
            self._json(200, {"ok": True})
            return

        if path == "/api/resolve-user":
            try:
                body = self._read_json()
                username = str((body or {}).get("username") or "")
                user = resolve_username(username)
                session = create_session(user, c)
                self._json(200, {"user": user, "token": session})
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(502, {"error": f"Roblox lookup failed: {e}"})
            return

        self._json(404, {"error": "Not found"})

    def _redirect_app(
        self, c: dict[str, str], *, token: str | None = None, error: str | None = None
    ) -> None:
        app = c["app_url"]
        parts = urllib.parse.urlsplit(app)
        q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        # Prefer hash so the token is less likely to hit server logs on static hosts
        frag_bits = []
        if token:
            frag_bits.append(f"roblox_token={urllib.parse.quote(token)}")
        if error:
            frag_bits.append(f"roblox_error={urllib.parse.quote(error)}")
        frag = "&".join(frag_bits)
        loc = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, parts.query, frag)
        )
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()


def main() -> None:
    load_dotenv()
    c = cfg()
    host = c["host"]
    port = int(c["port"])
    oauth = bool(c["client_id"] and c["client_secret"])
    print(f"Lunix Roblox auth server on http://{host}:{port}")
    print(f"  Public auth URL : {c['auth_public_url']}")
    print(f"  Redirect URI    : {c['redirect_uri']}")
    print(f"  App return URL  : {c['app_url']}")
    print(f"  OAuth ready     : {oauth}")
    print(f"  Username link   : always on")
    if not oauth:
        print(
            "  Tip: add ROBLOX_CLIENT_ID / ROBLOX_CLIENT_SECRET to .env "
            "for Sign in with Roblox."
        )
    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
