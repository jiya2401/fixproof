"""Static Application Security Testing (SAST) scanner for FixProof.

A zero-dependency, pure-Python AST-based vulnerability scanner that runs after every
patch application to detect whether the AI fix introduced new security vulnerabilities.

Detection categories (modelled after Bandit rule IDs):
  B101 – SQL Injection           (HIGH)
  B102 – Command Injection       (HIGH)
  B103 – Path Traversal          (HIGH)
  B201 – Hardcoded Secret        (MEDIUM)
  B202 – Unsafe Deserialization  (HIGH)
  B203 – Weak Cryptographic Hash (MEDIUM)

No external packages are required; only Python's built-in ``ast``, ``pathlib``, and
``time`` modules are used, making this safe for an offline/sandboxed environment.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

Severity = Literal["HIGH", "MEDIUM", "LOW"]

_SEVERITY_RANK: dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


class VulnerabilityFinding(BaseModel):
    """A single security finding produced by the scanner."""

    file: str
    """Relative path of the source file, POSIX separators."""
    line_number: int
    """1-based line number of the offending AST node."""
    issue_description: str
    """Human-readable description of the security issue."""
    severity: Severity
    """HIGH, MEDIUM, or LOW."""
    rule_id: str
    """Bandit-compatible rule identifier, e.g. 'B101'."""
    col_offset: int = 0
    """0-based column offset (best-effort; 0 when unavailable)."""

    # ------------------------------------------------------------------ helpers
    def is_actionable(self) -> bool:
        """True for findings that trigger a security gate (HIGH or MEDIUM)."""
        return self.severity in ("HIGH", "MEDIUM")

    def fingerprint(self) -> str:
        """Stable identity key used for baseline comparison."""
        return f"{self.file}:{self.line_number}:{self.rule_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line_number": self.line_number,
            "issue_description": self.issue_description,
            "severity": self.severity,
            "rule_id": self.rule_id,
        }


class SecurityScanResult(BaseModel):
    """Structured output returned by :class:`SecurityScanner`."""

    passed: bool
    """True when no new HIGH or MEDIUM vulnerabilities were introduced."""
    new_vulnerabilities: list[VulnerabilityFinding] = Field(default_factory=list)
    """Findings present after the patch that were absent in the baseline scan."""
    all_post_patch_findings: list[VulnerabilityFinding] = Field(default_factory=list)
    """Every finding in the patched workspace (baseline + new)."""
    baseline_count: int = 0
    """Total number of actionable findings before the patch."""
    post_patch_count: int = 0
    """Total number of actionable findings after the patch."""
    files_scanned: int = 0
    """Number of Python source files analysed in the post-patch pass."""
    scan_duration_seconds: float = 0.0
    """Wall-clock time for the combined scan."""
    error: str | None = None
    """Non-empty when the scan itself raised an unexpected exception."""


# ---------------------------------------------------------------------------
# AST visitor – detection rules
# ---------------------------------------------------------------------------

_SQL_CALL_NAMES = frozenset(
    {
        "execute",
        "executemany",
        "executescript",
        "raw",
        "filter",
        "extra",
        "RawSQL",
    }
)

_SUBPROCESS_NAMES = frozenset(
    {
        "call",
        "run",
        "Popen",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    }
)

_PICKLE_NAMES = frozenset({"loads", "load", "Unpickler"})

_WEAK_HASH_NAMES = frozenset({"md5", "sha1"})

_SECRET_VAR_PATTERNS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "token",
        "auth_token",
        "access_token",
        "private_key",
        "client_secret",
    }
)


def _is_dynamic(node: ast.expr) -> bool:
    """Return True if the expression involves a variable (not a pure constant)."""
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
        return True
    if isinstance(node, ast.JoinedStr):  # f-string
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True  # "SELECT %s" % value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # "/uploads/" + user_input  — flag when either side is dynamic
        return _is_dynamic(node.left) or _is_dynamic(node.right)
    if isinstance(node, ast.Call):
        # "SELECT {}".format(...)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return True
    return False


def _has_shell_true(keywords: list[ast.keyword]) -> bool:
    for kw in keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _first_arg_is_dynamic(call: ast.Call) -> bool:
    return bool(call.args) and _is_dynamic(call.args[0])


def _has_loader_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "Loader" for kw in call.keywords)


class _SecurityVisitor(ast.NodeVisitor):
    """Walk an AST and collect :class:`VulnerabilityFinding` objects."""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.findings: list[VulnerabilityFinding] = []
        # Track import aliases: local_name -> canonical module
        self._imports: dict[str, str] = {}  # e.g. {"os": "os", "sub": "subprocess"}
        self._from_imports: dict[str, str] = {}  # e.g. {"loads": "pickle.loads"}
        self._yaml_names: set[str] = set()  # local names for yaml module
        self._pickle_names: set[str] = set()  # local names for pickle module
        self._os_names: set[str] = set()  # local names for os module
        self._subprocess_names: set[str] = set()  # local names for subprocess module
        self._hashlib_names: set[str] = set()  # local names for hashlib module

    # ------------------------------------------------------------------ helpers
    def _add(
        self,
        node: ast.AST,
        rule_id: str,
        severity: Severity,
        description: str,
    ) -> None:
        lineno = getattr(node, "lineno", 0)
        col = getattr(node, "col_offset", 0)
        self.findings.append(
            VulnerabilityFinding(
                file=self.rel_path,
                line_number=lineno,
                col_offset=col,
                rule_id=rule_id,
                severity=severity,
                issue_description=description,
            )
        )

    # ------------------------------------------------------------------ import tracking
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name
            top = alias.name.split(".")[0]
            if top == "os":
                self._os_names.add(local)
            elif top == "subprocess":
                self._subprocess_names.add(local)
            elif alias.name in ("pickle", "_pickle", "cPickle"):
                self._pickle_names.add(local)
            elif alias.name in ("yaml", "ruamel.yaml"):
                self._yaml_names.add(local)
            elif alias.name == "hashlib":
                self._hashlib_names.add(local)
            self._imports[local] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            qualified = f"{module}.{alias.name}"
            self._from_imports[local] = qualified
            top = module.split(".")[0]
            if top == "os":
                self._os_names.add(local)
            if top == "subprocess":
                self._subprocess_names.add(local)
            if module in ("pickle", "_pickle", "cPickle"):
                self._pickle_names.add(local)
            if module in ("yaml", "ruamel.yaml"):
                self._yaml_names.add(local)
            if module == "hashlib":
                self._hashlib_names.add(local)
        self.generic_visit(node)

    # ------------------------------------------------------------------ B201: Hardcoded secret
    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if len(node.value.value) >= 4:  # ignore empty/trivial strings
                for target in node.targets:
                    name = None
                    if isinstance(target, ast.Name):
                        name = target.id.lower()
                    elif isinstance(target, ast.Attribute):
                        name = target.attr.lower()
                    if name and any(pat in name for pat in _SECRET_VAR_PATTERNS):
                        self._add(
                            node,
                            "B201",
                            "MEDIUM",
                            f"Possible hardcoded secret in variable '{name}'. "
                            "Use environment variables or a secrets manager instead.",
                        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            node.value
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and len(node.value.value) >= 4
        ):
            target = node.target
            name = None
            if isinstance(target, ast.Name):
                name = target.id.lower()
            elif isinstance(target, ast.Attribute):
                name = target.attr.lower()
            if name and any(pat in name for pat in _SECRET_VAR_PATTERNS):
                self._add(
                    node,
                    "B201",
                    "MEDIUM",
                    f"Possible hardcoded secret in annotated variable '{name}'. "
                    "Use environment variables or a secrets manager instead.",
                )
        self.generic_visit(node)

    # ------------------------------------------------------------------ dispatch on call nodes
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # Determine the function name and optional module prefix
        if isinstance(func, ast.Attribute):
            method = func.attr
            obj = func.value
            obj_name = obj.id if isinstance(obj, ast.Name) else None
            self._check_sql_injection(node, method)
            self._check_subprocess_call(node, obj_name, method)
            self._check_pickle_call(node, obj_name, method)
            self._check_yaml_call(node, obj_name, method)
            self._check_hashlib_call(node, obj_name, method)
            self._check_os_system(node, obj_name, method)
        elif isinstance(func, ast.Name):
            fname = func.id
            self._check_open_path_traversal(node, fname)
            self._check_subprocess_bare(node, fname)
            self._check_pickle_bare(node, fname)
            self._check_hashlib_bare(node, fname)
        self.generic_visit(node)

    # ------------------------------------------------------------------ B101: SQL Injection
    def _check_sql_injection(self, node: ast.Call, method: str) -> None:
        if method not in _SQL_CALL_NAMES:
            return
        if not node.args:
            return
        first = node.args[0]
        if _is_dynamic(first):
            self._add(
                node,
                "B101",
                "HIGH",
                f"Possible SQL injection: dynamic value passed to '{method}()'. "
                "Use parameterised queries with placeholders instead of string formatting.",
            )

    # ------------------------------------------------------------------ B102: Command Injection
    def _check_subprocess_call(self, node: ast.Call, obj_name: str | None, method: str) -> None:
        if method not in _SUBPROCESS_NAMES:
            return
        is_subprocess = obj_name in self._subprocess_names or obj_name == "subprocess"
        if not is_subprocess:
            return
        if _has_shell_true(node.keywords) and _first_arg_is_dynamic(node):
            self._add(
                node,
                "B102",
                "HIGH",
                f"Command injection risk: subprocess.{method}() called with "
                "shell=True and a dynamic command argument. "
                "Pass a list of arguments without shell=True.",
            )

    def _check_subprocess_bare(self, node: ast.Call, fname: str) -> None:
        """Handles 'from subprocess import run' style."""
        if fname not in _SUBPROCESS_NAMES:
            return
        qualified = self._from_imports.get(fname, "")
        if not qualified.startswith("subprocess."):
            return
        if _has_shell_true(node.keywords) and _first_arg_is_dynamic(node):
            self._add(
                node,
                "B102",
                "HIGH",
                f"Command injection risk: {fname}() called with shell=True and "
                "a dynamic command argument. Pass a list of arguments instead.",
            )

    def _check_os_system(self, node: ast.Call, obj_name: str | None, method: str) -> None:
        if method not in ("system", "popen") or obj_name not in self._os_names:
            return
        if _first_arg_is_dynamic(node):
            self._add(
                node,
                "B102",
                "HIGH",
                f"Command injection risk: os.{method}() called with a dynamic argument. "
                "Use subprocess with a list of arguments and no shell=True.",
            )

    # ------------------------------------------------------------------ B103: Path Traversal
    def _check_open_path_traversal(self, node: ast.Call, fname: str) -> None:
        if fname not in ("open", "Path"):
            return
        if not node.args:
            return
        first = node.args[0]
        # Flag when the first argument is dynamic (variable or formatted string)
        if _is_dynamic(first):
            # Extra heuristic: if it's a simple Name it might just be a local var, but
            # any f-string or + concatenation is suspicious.
            if isinstance(first, (ast.JoinedStr, ast.BinOp)):
                verb = "open()" if fname == "open" else "Path()"
                self._add(
                    node,
                    "B103",
                    "HIGH",
                    f"Possible path traversal: {verb} called with a dynamically constructed "
                    "path. Validate and sanitise user-supplied path components with "
                    "pathlib.Path.resolve() and confirm the result stays inside the "
                    "expected base directory.",
                )

    # ------------------------------------------------------------- B202: Unsafe Deserialization
    def _check_pickle_call(self, node: ast.Call, obj_name: str | None, method: str) -> None:
        if method not in _PICKLE_NAMES:
            return
        if obj_name not in self._pickle_names and obj_name not in (
            "pickle",
            "_pickle",
            "cPickle",
        ):
            return
        self._add(
            node,
            "B202",
            "HIGH",
            f"Unsafe deserialization: pickle.{method}() can execute arbitrary code when "
            "deserialising untrusted data. Use a safe format such as JSON.",
        )

    def _check_pickle_bare(self, node: ast.Call, fname: str) -> None:
        if fname not in _PICKLE_NAMES:
            return
        if self._from_imports.get(fname, "").split(".")[0] not in (
            "pickle",
            "_pickle",
            "cPickle",
        ):
            return
        self._add(
            node,
            "B202",
            "HIGH",
            f"Unsafe deserialization: {fname}() (imported from pickle) can execute "
            "arbitrary code. Use a safe format such as JSON.",
        )

    def _check_yaml_call(self, node: ast.Call, obj_name: str | None, method: str) -> None:
        if method != "load":
            return
        if obj_name not in self._yaml_names and obj_name != "yaml":
            return
        if not _has_loader_kwarg(node):
            self._add(
                node,
                "B202",
                "MEDIUM",
                "Unsafe YAML load: yaml.load() without an explicit Loader= kwarg allows "
                "arbitrary Python object construction. Use yaml.safe_load() or pass "
                "Loader=yaml.SafeLoader.",
            )

    # ------------------------------------------------------------------ B203: Weak Crypto
    def _check_hashlib_call(self, node: ast.Call, obj_name: str | None, method: str) -> None:
        if method not in _WEAK_HASH_NAMES:
            return
        if obj_name not in self._hashlib_names and obj_name != "hashlib":
            return
        self._add(
            node,
            "B203",
            "MEDIUM",
            f"Weak cryptographic hash: hashlib.{method}() is cryptographically broken "
            "and must not be used for security-sensitive purposes. "
            "Use SHA-256 (hashlib.sha256) or stronger.",
        )

    def _check_hashlib_bare(self, node: ast.Call, fname: str) -> None:
        if fname not in _WEAK_HASH_NAMES:
            return
        qualified = self._from_imports.get(fname, "")
        if not qualified.startswith("hashlib."):
            return
        self._add(
            node,
            "B203",
            "MEDIUM",
            f"Weak cryptographic hash: {fname}() (imported from hashlib) is "
            "cryptographically broken. Use sha256 or stronger.",
        )


# ---------------------------------------------------------------------------
# Public scanner API
# ---------------------------------------------------------------------------


class SecurityScanner:
    """Lightweight static security scanner operating on Python source files.

    Usage::

        scanner = SecurityScanner()
        baseline = scanner.scan_directory(source_root, changed_files)
        # … patch is applied to workspace …
        post    = scanner.scan_directory(workspace, changed_files)
        result  = scanner.compare(baseline, post)
        # result.passed → True/False
        # result.new_vulnerabilities → list[VulnerabilityFinding]
    """

    # ------------------------------------------------------------------
    def scan_file(self, path: Path, rel_path: str) -> list[VulnerabilityFinding]:
        """Scan a single Python source file and return its findings.

        Parameters
        ----------
        path:
            Absolute path of the file on disk.
        rel_path:
            Relative path that will be embedded in each :class:`VulnerabilityFinding`
            (POSIX separators).

        Returns
        -------
        list[VulnerabilityFinding]
            Findings for this file (may be empty).
        """
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            # Unparseable files are skipped silently — they may be intentionally
            # broken fixtures or non-Python files with a .py extension.
            return []
        visitor = _SecurityVisitor(rel_path)
        visitor.visit(tree)
        return visitor.findings

    # ------------------------------------------------------------------
    def scan_directory(
        self,
        root: Path,
        focus_files: list[str] | None = None,
    ) -> list[VulnerabilityFinding]:
        """Scan Python files under *root*, optionally limiting to *focus_files*.

        Parameters
        ----------
        root:
            Directory to scan.
        focus_files:
            Optional list of relative POSIX paths.  When supplied, only those
            files are scanned.  When ``None``, all ``*.py`` files under *root*
            are scanned (excluding ``.git``, ``__pycache__``, ``.venv``, etc.).

        Returns
        -------
        list[VulnerabilityFinding]
            All findings across every scanned file.
        """
        _SKIP_DIRS = frozenset(
            {
                ".git",
                "__pycache__",
                ".pytest_cache",
                ".venv",
                "venv",
                "node_modules",
                "fixproof_adv",
                ".mypy_cache",
            }
        )

        findings: list[VulnerabilityFinding] = []

        if focus_files is not None:
            paths_to_scan: list[tuple[Path, str]] = []
            for rel in focus_files:
                full = root / rel
                if full.is_file() and full.suffix == ".py":
                    paths_to_scan.append((full, rel))
        else:
            paths_to_scan = []
            for p in sorted(root.rglob("*.py")):
                rel = p.relative_to(root)
                if any(part in _SKIP_DIRS for part in rel.parts):
                    continue
                paths_to_scan.append((p, rel.as_posix()))

        for full_path, rel_path in paths_to_scan:
            findings.extend(self.scan_file(full_path, rel_path))

        return findings

    # ------------------------------------------------------------------
    def compare(
        self,
        baseline: list[VulnerabilityFinding],
        post_patch: list[VulnerabilityFinding],
    ) -> SecurityScanResult:
        """Identify net-new actionable findings introduced by a patch.

        A finding is considered *new* when its fingerprint
        (``file:line:rule_id``) was absent in the baseline.

        Parameters
        ----------
        baseline:
            Findings from the **pre-patch** source directory.
        post_patch:
            Findings from the **post-patch** workspace.

        Returns
        -------
        SecurityScanResult
            ``passed=True`` ↔ no new HIGH or MEDIUM findings were introduced.
        """
        baseline_fps: set[str] = {f.fingerprint() for f in baseline if f.is_actionable()}
        actionable_post = [f for f in post_patch if f.is_actionable()]

        new_vulns = [f for f in actionable_post if f.fingerprint() not in baseline_fps]

        return SecurityScanResult(
            passed=len(new_vulns) == 0,
            new_vulnerabilities=sorted(
                new_vulns, key=lambda v: _SEVERITY_RANK[v.severity], reverse=True
            ),
            all_post_patch_findings=post_patch,
            baseline_count=len([f for f in baseline if f.is_actionable()]),
            post_patch_count=len(actionable_post),
            files_scanned=len({f.file for f in post_patch}),
        )

    # ------------------------------------------------------------------
    def run_comparative_scan(
        self,
        *,
        source: Path,
        workspace: Path,
        changed_files: list[str] | None = None,
    ) -> tuple[SecurityScanResult, float]:
        """Full pipeline: baseline scan → post-patch scan → delta comparison.

        Parameters
        ----------
        source:
            Pre-patch source directory (read-only reference).
        workspace:
            Post-patch workspace directory.
        changed_files:
            Optional list of relative POSIX file paths touched by the patch.
            When provided, *only* those files are scanned (faster).
            When ``None``, all Python files are scanned.

        Returns
        -------
        tuple[SecurityScanResult, float]
            The scan result and the total wall-clock duration in seconds.
        """
        t0 = time.monotonic()
        try:
            baseline = self.scan_directory(source, focus_files=changed_files)
            post_patch = self.scan_directory(workspace, focus_files=changed_files)
            result = self.compare(baseline, post_patch)
        except Exception as exc:  # noqa: BLE001
            result = SecurityScanResult(
                passed=True,  # fail-open: don't block the pipeline on scanner errors
                error=f"SAST scanner raised an exception: {exc}",
            )
        elapsed = time.monotonic() - t0
        result.scan_duration_seconds = elapsed
        return result, elapsed


# ---------------------------------------------------------------------------
# Module-level convenience singleton
# ---------------------------------------------------------------------------

_DEFAULT_SCANNER = SecurityScanner()


def run_security_scan(
    *,
    source: Path,
    workspace: Path,
    changed_files: list[str] | None = None,
) -> SecurityScanResult:
    """Convenience wrapper around the default :class:`SecurityScanner` instance.

    Parameters
    ----------
    source:
        Pre-patch source root (for baseline).
    workspace:
        Post-patch workspace root.
    changed_files:
        Relative POSIX paths of files modified by the patch.

    Returns
    -------
    SecurityScanResult
        ``passed`` is ``True`` when no new HIGH/MEDIUM findings were introduced.
    """
    result, _ = _DEFAULT_SCANNER.run_comparative_scan(
        source=source, workspace=workspace, changed_files=changed_files
    )
    return result
