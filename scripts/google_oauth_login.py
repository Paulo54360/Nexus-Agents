"""One-click OAuth 2.0 login generating tokens for both Gmail and Google Calendar MCP servers."""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SECRETS_DIR = Path("/app/secrets")
CREDENTIALS_FILE = SECRETS_DIR / "google_credentials.json"
GMAIL_TOKEN_FILE = SECRETS_DIR / "gmail_token.json"
CALENDAR_TOKEN_FILE = SECRETS_DIR / "calendar_token.json"

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/oauth2callback"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar",
]


def main() -> None:
    if not CREDENTIALS_FILE.exists():
        print(f"ERREUR: {CREDENTIALS_FILE} introuvable.", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    cfg = raw.get("installed") or raw.get("web")
    if not cfg:
        print("ERREUR: format google_credentials.json non reconnu.", file=sys.stderr)
        sys.exit(1)

    client_id = cfg["client_id"]
    client_secret = cfg["client_secret"]
    auth_uri = cfg.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    token_uri = cfg.get("token_uri", "https://oauth2.googleapis.com/token")

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    auth_url = f"{auth_uri}?{params}"

    auth_code: dict[str, str | None] = {"code": None, "error": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                auth_code["code"] = qs["code"][0]
                body = (
                    "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                    "<h1>&#9989; Connexion Google reussie !</h1>"
                    "<p>Tu peux fermer cet onglet et revenir dans PowerShell.</p>"
                    "</body></html>"
                )
                self.send_response(200)
            else:
                auth_code["error"] = qs.get("error", ["unknown"])[0]
                body = f"<html><body><h1>Erreur OAuth: {auth_code['error']}</h1></body></html>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
    print("\n======================================================================")
    print("OUVRE CE LIEN DANS TON NAVIGATEUR POUR AUTORISER GMAIL + CALENDAR :")
    print(auth_url)
    print("======================================================================\n", flush=True)

    while auth_code["code"] is None and auth_code["error"] is None:
        server.handle_request()
    server.server_close()

    if auth_code["error"] or not auth_code["code"]:
        print(f"ERREUR OAuth: {auth_code['error']}", file=sys.stderr)
        sys.exit(1)

    token_data = urllib.parse.urlencode(
        {
            "code": auth_code["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_uri,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    expiry_ms = int((time.time() + int(tokens.get("expires_in", 3600))) * 1000)
    token_payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "scope": tokens.get("scope", " ".join(SCOPES)),
        "token_type": tokens.get("token_type", "Bearer"),
        "expiry_date": expiry_ms,
    }

    GMAIL_TOKEN_FILE.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")
    CALENDAR_TOKEN_FILE.write_text(
        json.dumps({"normal": token_payload}, indent=2), encoding="utf-8"
    )
    print("OK! Tokens sauvegardes dans secrets/gmail_token.json et secrets/calendar_token.json")


if __name__ == "__main__":
    main()
