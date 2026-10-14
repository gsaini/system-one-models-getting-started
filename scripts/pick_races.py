"""List good Wikiracing targets in the snapshot: pages two hops from a root, reachable through only a
few intermediate pages, with no words in common with the start (so the keyword baseline can't win by
string matching). Hand-pick from the output into data/wiki_races.json."""

from __future__ import annotations

import sys
from collections import defaultdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
from systemone.data import load_snapshot
from systemone.experiments.wikirace import words


def main() -> int:
    snap = load_snapshot()
    for root in snap.roots:
        depth1 = set(snap.links(root))
        parents: dict[str, set[str]] = defaultdict(set)
        for mid in depth1:
            for leaf in snap.links(mid):
                if leaf not in depth1 and leaf != root:
                    parents[leaf].add(mid)
        picks = [
            (leaf, sorted(ps))
            for leaf, ps in parents.items()
            if 1 <= len(ps) <= 2 and not (words(leaf) & words(root)) and all(not (words(leaf) & words(p)) for p in ps)
        ]
        picks.sort(key=lambda x: (len(x[1]), x[0]))
        print(f"\n== {root}: {len(depth1)} direct links, {len(parents)} pages at depth 2, {len(picks)} candidates ==")
        for leaf, ps in picks[:400]:
            print(f"  {leaf!r:60} via {ps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
