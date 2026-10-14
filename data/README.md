# Bundled data

## `sms_spam_sample.jsonl` — 1,000 labelled SMS messages

A sample of the **SMS Spam Collection v.1** (Almeida, Hidalgo & Yamakami, 2011), 5,574 English text
messages labelled `ham` or `spam`, published by the UCI Machine Learning Repository under
**CC BY 4.0**: <https://archive.ics.uci.edu/dataset/228/sms+spam+collection>.

How the sample was made: exact-duplicate messages were removed (5,159 unique remained, 642 spam), the
rest were shuffled with a fixed seed, and 130 spam + 870 ham were kept to preserve the corpus's
natural ratio (≈13% spam). Each row is `{"id", "label", "text"}`; `id` is the first 10 hex characters of
the SHA-1 of the text.

Citation: Almeida, T.A., Gómez Hidalgo, J.M., Yamakami, A. *Contributions to the Study of SMS Spam
Filtering: New Collection and Results.* Proceedings of the 2011 ACM Symposium on Document Engineering
(DOCENG'11), Mountain View, CA, USA, 2011.

## `wiki_snapshot.json.gz` — Wikipedia link lists

Outgoing article links (namespace 0) for two root pages and every page they link to, fetched from the
English Wikipedia API by [`scripts/build_wiki_snapshot.py`](../scripts/build_wiki_snapshot.py). Only
titles and link structure are stored, no article text. Wikipedia content is **CC BY-SA 4.0**:
<https://en.wikipedia.org/wiki/Wikipedia:Copyrights>. The `built` field records the fetch time; link
lists change, so a rebuild will differ.

## `wiki_races.json` — the races

Hand-picked `(start, target)` pairs from the snapshot, each with the shortest possible hop count inside
it, chosen so that the start and target share no words (string matching can't win) and the target is
reachable through only one or two intermediate pages (there is a real decision to make).
