"""Phase 0 spike: log in once and dump raw Forever API responses to samples/.

Run with: uv run character-planner-spike

Opens your browser to Battle.net, catches the OAuth callback on the redirect URI,
then saves every probed endpoint's status and JSON body to samples/<timestamp>/.
The access token is never written to disk.
"""

import json
import sys
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from character_planner.blizzard import oauth
from character_planner.blizzard.client import ApiResult, BlizzardClient
from character_planner.config import Settings

SAMPLES_DIR = Path("samples")
LOGIN_TIMEOUT_SECONDS = 180


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}  # noqa: RUF012 - one-shot server, shared on purpose
    done = threading.Event()

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        _CallbackHandler.result = {key: values[0] for key, values in query.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Login received. You can close this tab and return to the terminal.")
        _CallbackHandler.done.set()

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep the terminal quiet; the URL holds the one-time code


def wait_for_callback(settings: Settings) -> dict[str, str]:
    redirect = urlparse(settings.bnet_redirect_uri)
    host, port = redirect.hostname or "localhost", redirect.port or 80
    server = HTTPServer((host, port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not _CallbackHandler.done.wait(LOGIN_TIMEOUT_SECONDS):
            raise TimeoutError(f"No OAuth callback within {LOGIN_TIMEOUT_SECONDS}s")
        return _CallbackHandler.result
    finally:
        server.shutdown()


def save(results: list[ApiResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, object]] = []
    for result in results:
        path = out_dir / f"{result.kind}.json"
        record = {"url": result.url, "status": result.status, "body": result.body}
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        summary.append({"kind": result.kind, "status": result.status})
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    settings = Settings()
    if not settings.has_credentials:
        print("Set BNET_CLIENT_ID and BNET_CLIENT_SECRET in .env first (see .env.example).")
        return 1

    state = oauth.new_state()
    url = oauth.authorize_url(settings, state)
    print("Opening Battle.net login in your browser. If it doesn't open, visit:\n" + url)
    webbrowser.open(url)

    callback = wait_for_callback(settings)
    if callback.get("state") != state:
        print("State mismatch on the callback; aborting.")
        return 1
    if "code" not in callback:
        print(f"Login failed: {callback.get('error_description') or callback}")
        return 1

    token = oauth.exchange_code(settings, callback["code"])
    print(f"Token scope: {token.scope or '(none reported)'}")

    with BlizzardClient(settings, token) as client:
        results = [client.account_profile(), *client.all_character_data()]

    out_dir = SAMPLES_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    save(results, out_dir)

    print(f"\nSaved {len(results)} responses to {out_dir}:")
    for result in results:
        print(f"  {result.status}  {result.kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
