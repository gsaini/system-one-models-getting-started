"""`systemone ui`: a local web playground. Type a message, watch every player fill in the same form.

Standard library only. The page asks each player separately, so a fast player's answers appear
while a slow one is still working: the speed difference is something you see, not a number.
Binds to 127.0.0.1; nothing is exposed to the network.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from systemone.arms import Arm
from systemone.baseline import Answerer
from systemone.data import Race, Snapshot
from systemone.experiments import wikirace
from systemone.playground import FORMS, ask

PAGE = Path(__file__).with_name("index.html")
MAX_MESSAGE = 4000


class BadRequest(ValueError):
    pass


class Playground:
    def __init__(self, make_arms: Callable[[Answerer], list[Arm]], snapshot: Snapshot, races: list[Race]) -> None:
        self.arms = {key: make_arms(form.answerer) for key, form in FORMS.items()}
        self.race_arms = make_arms(wikirace.answerer)
        self.snapshot, self.races = snapshot, races
        # One request at a time per player: an Arm's call log isn't meant to be shared mid-call.
        self.locks = {id(a): threading.Lock() for arms in [*self.arms.values(), self.race_arms] for a in arms}

    def config(self) -> dict[str, Any]:
        return {
            "players": [a.name for a in self.race_arms],
            "forms": {key: form.describe() for key, form in FORMS.items()},
            "races": [asdict(r) for r in self.races],
        }

    def _pick(self, arms: list[Arm], body: dict[str, Any]) -> Arm:
        try:
            return arms[int(body["player"])]
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            raise BadRequest("Unknown player.") from exc

    def ask(self, body: dict[str, Any]) -> dict[str, Any]:
        form = FORMS.get(str(body.get("form")))
        if form is None:
            raise BadRequest("Unknown form.")
        message = str(body.get("message", "")).strip()
        if not message:
            raise BadRequest("Type a message first.")
        arm = self._pick(self.arms[form.key], body)
        with self.locks[id(arm)]:
            return ask(arm, form, message[:MAX_MESSAGE])

    def race(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            race = self.races[int(body["race"])]
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            raise BadRequest("Unknown race.") from exc
        arm = self._pick(self.race_arms, body)
        timings: list[float] = []
        with self.locks[id(arm)]:
            mark, started = len(arm.calls), time.perf_counter()

            def on_step(_: wikirace.Step) -> None:
                nonlocal mark
                timings.append(sum(c.latency_ms for c in arm.calls[mark:]))
                mark = len(arm.calls)

            result = wikirace.navigate(arm, self.snapshot, race, on_step=on_step)
            total_ms = (time.perf_counter() - started) * 1000
        out = asdict(result) | {"hops": result.hops, "shortest": race.shortest, "ms": round(total_ms)}
        for step, ms in zip(out["steps"], timings, strict=True):
            step["ms"] = round(ms)
        return out


def handler_for(playground: Playground) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, default=str).encode(), "application/json")

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/config":
                self._json(200, playground.config())
            else:
                self._json(404, {"error": "Not found."})

        def do_POST(self) -> None:
            routes = {"/api/ask": playground.ask, "/api/race": playground.race}
            if self.path not in routes:
                self._json(404, {"error": "Not found."})
                return
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 64_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise BadRequest("Send a JSON object.")
                self._json(200, routes[self.path](body))
            except (BadRequest, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc) or "Send a JSON object."})

        def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
            pass

    return Handler


def serve(playground: Playground, *, port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(playground))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Playground running at {url}  (players: {', '.join(playground.config()['players'])})", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
