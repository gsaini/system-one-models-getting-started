# The claims, and how each one is tested

Source: [*Introducing System One Models & Jev*](https://typesafe.ai/blog/introducing-system-one-models-and-jev), Diogo Almeida, TypeSafe, 2026-10-13. Quotes are from the post or TypeSafe's docs. "Independent" means tests by people outside TypeSafe, as they reported them; nothing here was re-run.

## 1. A function call, not a chat

> "a frontier-intelligence function call: unstructured state in, typed probabilistic decisions out"

**Test:** `systemone demo`. One request carries an account record and a message plus eight questions: two Choices, two Scores, four Nouls. The answers come back as the option you listed, a level on the rubric you wrote, or a probability. There is no string to parse and nothing to validate.

**What to notice:** the same call runs against Jev, against Claude through TypeSafe's adapter, and against keyword rules. The *interface* is the product. Whether the *answers* are good is what the other experiments measure.

**TypeSafe's own nuance:** Jev reads literally, is weak at counting, arithmetic, and date comparison, and loses accuracy when the state carries detail the question doesn't need ([Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)). The demo's state is small and named on purpose.

## 2. Parallel evaluation

> Sampling: "sequential, one token at a time" (LLMs) vs "parallel, generating all outputs in one query" (System One). "Adding questions barely changes the response time."

**Test:** `systemone parallel`. A 230-word incident report and 32 labelled yes/no questions about it. For N in 1, 2, 4, 8, 16, 32: one request with N questions, then N requests with one question each. Reported: both latencies, tokens, whether the batched and single answers agree, and accuracy against the labels.

**What a confirmation looks like:** the one-request latency stays roughly flat as N grows while the sequential total grows linearly, with agreement near 100%. TypeSafe's own [parallel-questions cookbook](https://docs.typesafe.ai/cookbooks/parallel_questions) reports 10× faster and 12× cheaper with unchanged answers on a 13-question briefing.

**Offline:** batching 32 questions costs 1,272 input tokens; 32 separate requests cost 12,079, because the report is re-sent every time. The token claim holds for any model; the latency claim is the one that needs the live run.

## 3. Calibrated decisions

> RLCD optimizes for "calibrated decisions". "Outcomes assigned a probability of 0.8 should occur about 80% of the time." LLMs "tend to be overconfident".

**Test:** `systemone calibration`. One Noul ("is `message` spam?") per message over a 1,000-message sample of the SMS Spam Collection, graded against its labels. Metrics: accuracy, precision/recall, **Brier score**, **ECE** (ten buckets), a **reliability table**, AUC, and a threshold sweep.

**What a confirmation looks like:** low ECE, and a reliability table where each bucket's actual spam rate is close to its mean probability. A model can be accurate and badly calibrated at once (everything at 0.99); the Brier score and ECE tell those apart.

**Independent evidence so far:**

- A pre-registered phishing benchmark ([beri.net, 2026-09-20](https://www.beri.net/article/typesafe-jev-typed-decision-model-calibration-decomposition-shadow-eval)) reported an **ECE of 0.107** out of distribution ("4.4× the 0.024 noise floor"), and on one ticket-priority question Jev was right **44.7%** of the time while assigning an average probability of **0.74**. The same study found the task's accuracy moved from 62.6% to 95.0% when one question was split into five narrow ones.
- A production-style product-matching run ([paddo.dev, 2026-09-30](https://paddo.dev/blog/thirty-cent-judge)): 9,081 pairs for $0.32 in 13 minutes, correct published matches up from 78% to 90%, and the warning *"when Jev is wrong, it is usually sure of itself."*

**TypeSafe's own nuance:** "Calibration is measured across groups of predictions; it does not guarantee that an individual answer is correct" ([System One](https://docs.typesafe.ai/concepts/system-one)).

## 4. Hallucination and type safety

> Type errors: Jev 0%, "mathematically impossible", because the output is schema-matched by construction.

**Test:** every run's per-arm table has a `malformed retries` column. For Jev it is zero by construction. The LLM arm uses the adapter with `structured_outputs=True`, which is Claude's schema-constrained output mode, so it should also be zero; the adapter still validates and counts corrective retries, and `normalize_probabilities=True` rescales a distribution that doesn't sum to one instead of failing.

**What this means:** schema validity is not what separates the two any more. Modern LLM APIs guarantee the JSON shape too. What Jev adds is that the *probabilities* are the output, trained to be calibrated and returned for every option in one pass, rather than numbers an LLM writes into a JSON field. Whether those probabilities are better is experiment 3.

**TypeSafe's own nuance:** the post says its LLM hallucination figures come from OpenRouter traffic and "may be biased by OpenRouter routing", and that "a valid action can still be wrong".

## 5. Speed and cost

> "70ms to 500ms end-to-end", "$0.042 per MTok", output "FREE (too cheap to meter)". "40× to 200× faster" per call; "193.6× faster, 444.6× cheaper" on workflows.

**Test:** every run records latency p50/p95 and tokens per arm, and prices them at list: Jev $42 per billion input tokens; Claude Opus 5.5 $4 / $20 per million input / output. The whole 1,000-message calibration run on Jev is about half a cent.

**What the headline measures:** TypeSafe's [workflow evals](https://evals.typesafe.ai/) score **agreement with consensus labels** that are "an average of the responses of GPT-6 Astra and Claude Fable 5.1", not human-labelled correctness. On that site's overview, Jev's workflow configuration is listed at 67.8% accuracy, $0.0004 and 0.4 s per case, against Opus 5's 73.1%, $0.1761 and 37.8 s. The post itself says the 193.6× figure is "on the higher end of real world gains", that speed evals ran "from founders' laptops on the West Coast", and that the reference labels "likely underestimate" some models.

**Independent evidence so far:** third-party tests compiled by [DataSci Ocean](https://datasciocean.com/en/ai-concept/jev-overview/) report roughly **5×–25× faster**, much smaller cost multiples than 444×, and accuracy "on par or slightly worse" than frontier models.

### The LLM arm

The comparison here is deliberately generous to the LLM: Claude Opus 5.5 (the current default Opus), structured outputs, and `effort: low`, because a yes/no judgment doesn't need the model's default `medium` and the cost gap is the question. Pass `--effort default` to run at Opus 5.5's default, or `--model claude-haiku-5-5` for the cheap end. TypeSafe's adapter sends `model`, `max_tokens`, `system`, `messages`, and `output_config.format`; [`providers.py`](../src/systemone/providers.py) adds `output_config.effort` and nothing else.

## 6. Wikiracing

> Navigate from one Wikipedia page to another through links. Cardinality "supported up to 255"; higher-cardinality choices use two-stage scoring.

**Test:** `systemone wikirace`. 14 races on a snapshot of real link lists. Code takes a direct link when the target is one hop away (exact lookup is code's job). Otherwise the candidates are the linked pages the snapshot knows, minus visited ones: **one Choice** when there are ≤255 of them, **Nouls in requests of 300 then a Choice over the top 100** above that, matching the post's description.

**What to notice:** the races were chosen so start and target share no words and the target sits behind one or two intermediate pages. The keyword baseline, which can only match words, solves 2 of 14. A model has to *know* that *Nudge* is behavioural economics or that *Garry Kasparov* is near *Alan Turing*. Hops versus the shortest path show how directly it gets there.

**Limits of this test:** the snapshot knows outgoing links for 257 pages, and no page links to more than 163 of them, so the two-stage path never triggers on the bundled data; it is covered by a unit test. The post also notes that its Wikiracing LLM baselines ran in non-reasoning modes and that two-stage scoring "causes occasional slowdowns".

## What this repo does not settle

- Nothing live was run while building it (no keys on the machine). The offline columns are a keyword baseline.
- Four experiments on two datasets and one link snapshot are a demonstration, not a benchmark. The post's own evals cover four workflows with consensus labels; independent studies so far are small.
- The labels in `parallel` were written by the same person who wrote the report.
