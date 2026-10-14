"""Bundled datasets: the SMS spam sample and the Wikipedia link snapshot. See data/README.md."""

from __future__ import annotations

import gzip
import json
import random
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class Message:
    id: str
    text: str
    spam: bool


def load_sms(limit: int | None = None, seed: int = 0) -> list[Message]:
    rows = [
        json.loads(line) for line in (DATA / "sms_spam_sample.jsonl").read_text(encoding="utf-8").splitlines() if line
    ]
    messages = [Message(r["id"], r["text"], r["label"] == "spam") for r in rows]
    if limit is not None and limit < len(messages):
        random.Random(seed).shuffle(messages)
        messages = messages[:limit]
    return messages


@dataclass(frozen=True)
class Snapshot:
    roots: tuple[str, ...]
    pages: dict[str, list[str]]  # title -> outgoing article links; a title absent here is a leaf

    def links(self, title: str) -> list[str]:
        return self.pages.get(title, [])

    def known(self, title: str) -> bool:
        return title in self.pages


@dataclass(frozen=True)
class Race:
    start: str
    target: str
    shortest: int  # hops on the shortest path inside the snapshot


def load_snapshot(path: Path = DATA / "wiki_snapshot.json.gz") -> Snapshot:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    return Snapshot(tuple(raw["roots"]), raw["pages"])


def load_races(path: Path = DATA / "wiki_races.json") -> list[Race]:
    return [Race(**r) for r in json.loads(path.read_text(encoding="utf-8"))]
