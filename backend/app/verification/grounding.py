"""Spec grounding for model-authored tests.

A model-written test only counts as *blocking* evidence if it quotes the sentence of the issue
or of the ORIGINAL source docstrings (before the patch) that it enforces, and that quote is
found verbatim (whitespace/case-insensitive). This stops invented requirements from rejecting a
patch, while keeping the verdict deterministic: no model decides whether a test is valid.

Limit: grounding proves traceability, not that the assertion follows from the quote. The
certificate shows the quote next to each counterexample for human review.
"""

import ast
import re
from pathlib import Path

from app.repair.patching import is_protected_path

MIN_QUOTE_CHARS = 15


def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("\"'`“”‘’").strip()
    return text.lower()


def build_spec_corpus(issue: str, source: Path) -> str:
    """Issue text plus docstrings of the original (pre-patch) non-test Python sources."""
    parts = [issue]
    for path in sorted(source.rglob("*.py")):
        rel = path.relative_to(source).as_posix()
        if rel.startswith(".") or "/." in rel or is_protected_path(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    parts.append(doc)
    return normalize("\n".join(parts))


def check_grounding(quote: str, corpus: str) -> tuple[bool, str]:
    """Return (grounded, reason). `corpus` must come from build_spec_corpus."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return False, f"spec quote missing or shorter than {MIN_QUOTE_CHARS} characters"
    if q not in corpus:
        return False, "spec quote not found verbatim in the issue or original docstrings"
    return True, "quote found in issue/original docstrings"
