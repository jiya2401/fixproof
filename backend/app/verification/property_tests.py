"""M6 boundary for Hypothesis-backed property verification.

Nemotron will propose invariants; this module will convert supported invariant templates
into executable Hypothesis tests. Unsupported natural-language properties must remain
explicitly unexecuted rather than being treated as passed.
"""
