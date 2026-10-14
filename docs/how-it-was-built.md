# How this repo was built

Built in one Claude Code session (Claude Fable 5.1) on 2026-10-14, the day after the post, from the request *"can you create a new GitHub repo to demonstrate this?"* with the post's URL.

## Order of work

1. **Read the post for its claims, not its summary.** Section by section: the definition, the LLM-vs-System-One table, every number and what it measures, the "Nuance" subsections the post attaches to each result, and the FAQ (two of its seven questions are answered). The claims became the experiment list.
2. **Read TypeSafe's docs and SDK source.** Models and pricing, the 255-option limit in the API reference, the confidence formulas, the Jev 1.13 weak-spots page, and `typesafe-sdk` 0.7.4's client (`transport=` is what makes the offline baseline possible).
3. **Found TypeSafe's own comparison tool.** The post links [`system-one-adapter-python`](https://github.com/typesafe-ai/system-one-adapter-python), a drop-in `TypeSafeClient` backed by LLM APIs. Reading its Anthropic provider showed it sends `output_config.format` (structured outputs) but no `effort`, so a small subclass adds that; the rest of the comparison arm is theirs, which keeps it apples-to-apples.
4. **Checked the Claude API shapes** against the current reference rather than memory: `output_config` holds both `format` and `effort`; Opus 5.5's effort default is `medium`; structured outputs guarantee the schema.
5. **Got real data.** The SMS Spam Collection (CC BY 4.0) was downloaded, de-duplicated, and sampled to 1,000 at the natural spam ratio. The Wikipedia snapshot was fetched from the API with an identifying User-Agent: two roots and every page they link to, 257 pages, 62,096 link entries, 447 KB gzipped. Races were picked by hand from a BFS listing so that start and target share no words and the target is behind one or two intermediate pages.
6. **Wrote the experiments, then the tests.** The offline baseline answers through the real SDK over a mock transport, so tests and CI exercise request building and response parsing without a key. Metrics were tested on inputs with known answers (perfect, coin-flip, and overconfident predictions) before being run on data.
7. **Ran everything offline and wrote down what it showed**, including the things that didn't work out: the two-stage path never triggers on the bundled snapshot, and keyword rules are strong on SMS spam.

## Decisions worth knowing

- **Offline numbers are labelled as the baseline everywhere.** The empty Jev and Claude columns are deliberate: nothing was run live, so nothing live is reported.
- **Code takes the direct link in Wikiracing.** An exact lookup is what System One's own guidance says to keep in code; asking a model would only add a chance to be wrong.
- **Ties go to the first option in the baseline.** That mirrors a documented Jev bias toward a Choice's first option, and it is why the baseline wanders to *A Review of General Semantics*.
- **Low effort for the LLM arm by default**, with `--effort default` available. The cost gap is the question; a generous LLM configuration makes a Jev win mean more and a Jev loss clearer.

## What was not done

- No live runs. No `TYPESAFE_API_KEY` or Anthropic credentials were on the machine.
- Patterns from the post that need a game or a browser (the Doom bot) are described, not built.
- The adapter's private helpers are imported for the effort provider, so `pyproject.toml` pins its minor version.
