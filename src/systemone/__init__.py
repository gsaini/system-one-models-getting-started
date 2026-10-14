"""System One models, tested: every claim in TypeSafe's launch post as an experiment you can run.

Three "arms" answer the same typed questions through the same `system_one(state, questions)` call:
Jev (the real thing), an LLM behind TypeSafe's own adapter, and an offline keyword baseline that
speaks the wire format. Code decides everything else and measures all of it.
"""
