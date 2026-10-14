"""Build the offline Wikipedia link snapshot used by the Wikiracing experiment.

Fetches the outgoing article links (namespace 0) of each ROOT page, then of every page the
roots link to. Pages at depth 2 are known by title only (no outgoing links): in a race they
are reachable, but you can't move on from them. Output: data/wiki_snapshot.json.gz

    {"built": "...", "roots": [...], "pages": {"Title": ["Linked title", ...]}}

Titles and link structure come from the English Wikipedia API (CC BY-SA 4.0); this script
sends an identifying User-Agent as the API etiquette asks. ~400 requests; a few minutes.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOTS = ["Thinking, Fast and Slow", "Bayes' theorem"]
API = "https://en.wikipedia.org/w/api.php"
UA = "system-one-models-getting-started/0.1 (https://github.com/gsaini/system-one-models-getting-started)"
OUT = Path(__file__).resolve().parents[1] / "data" / "wiki_snapshot.json.gz"
SKIP_PREFIXES = ("List of ", "Lists of ", "Index of ", "Outline of ", "Glossary of ", "Timeline of ")


def links_of(title: str) -> list[str]:
    out: list[str] = []
    params = {
        "action": "query",
        "prop": "links",
        "titles": title,
        "plnamespace": "0",
        "pllimit": "max",
        "format": "json",
    }
    while True:
        url = f"{API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        page = next(iter(data["query"]["pages"].values()))
        out += [link["title"] for link in page.get("links", [])]
        cont = data.get("continue", {}).get("plcontinue")
        if not cont:
            return [t for t in out if not t.startswith(SKIP_PREFIXES) and not t[:4].isdigit()]
        params["plcontinue"] = cont
        time.sleep(0.1)


def main() -> int:
    pages: dict[str, list[str]] = {}
    for root in ROOTS:
        pages[root] = links_of(root)
        print(f"{root}: {len(pages[root])} links", file=sys.stderr)
    frontier = sorted({t for root in ROOTS for t in pages[root] if t not in pages})
    for i, title in enumerate(frontier, 1):
        try:
            pages[title] = links_of(title)
        except Exception as exc:  # a missing or renamed page shouldn't sink the build
            print(f"  skip {title!r}: {exc}", file=sys.stderr)
            continue
        if i % 25 == 0:
            print(f"  {i}/{len(frontier)} pages", file=sys.stderr)
        time.sleep(0.15)
    snapshot = {"built": datetime.now(UTC).isoformat(timespec="seconds"), "roots": ROOTS, "pages": pages}
    OUT.parent.mkdir(exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    total_links = sum(len(v) for v in pages.values())
    print(f"wrote {OUT} — {len(pages)} pages with links, {total_links:,} link entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
