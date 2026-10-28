"""Tests for the Feature 4 SecurityScanner (backend/app/security.py).

Covers:
  - Individual detection rules (B101–B203) with both true-positive and true-negative cases
  - Multi-file directory scanning
  - Baseline comparison / delta logic (new vs pre-existing findings)
  - SecurityScanResult structure and the passed/failed contract
  - run_security_scan() convenience function
  - Edge cases: parse errors, empty files, no changed files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.security import (
    SecurityScanner,
    SecurityScanResult,
    VulnerabilityFinding,
    run_security_scan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_py(tmp_path: Path, name: str, code: str) -> Path:
    """Write *code* to ``tmp_path / name`` and return the path."""
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


def scan_code(tmp_path: Path, code: str, filename: str = "sample.py") -> list[VulnerabilityFinding]:
    """Write *code* to a temp file and scan it, returning findings."""
    scanner = SecurityScanner()
    p = write_py(tmp_path, filename, code)
    return scanner.scan_file(p, filename)


# ---------------------------------------------------------------------------
# B101 – SQL Injection
# ---------------------------------------------------------------------------


class TestB101SqlInjection:
    def test_fstring_in_execute(self, tmp_path: Path) -> None:
        code = (
            "import sqlite3\n"
            "def query(user_id):\n"
            "    conn = sqlite3.connect(':memory:')\n"
            "    conn.execute(f'SELECT * FROM users WHERE id = {user_id}')\n"
        )
        findings = scan_code(tmp_path, code)
        b101 = [f for f in findings if f.rule_id == "B101"]
        assert b101, "Expected B101 for f-string in execute()"
        assert b101[0].severity == "HIGH"
        assert "SQL injection" in b101[0].issue_description.lower() or "sql" in b101[0].issue_description.lower()

    def test_format_in_execute(self, tmp_path: Path) -> None:
        code = (
            "def run(cursor, table):\n"
            "    cursor.execute('DELETE FROM {} WHERE 1=1'.format(table))\n"
        )
        findings = scan_code(tmp_path, code)
        b101 = [f for f in findings if f.rule_id == "B101"]
        assert b101, "Expected B101 for .format() in execute()"

    def test_percent_format_in_execute(self, tmp_path: Path) -> None:
        code = (
            "def run(cursor, name):\n"
            "    cursor.execute('SELECT * FROM t WHERE name = %s' % name)\n"
        )
        findings = scan_code(tmp_path, code)
        b101 = [f for f in findings if f.rule_id == "B101"]
        assert b101, "Expected B101 for %-format in execute()"

    def test_parameterised_query_is_clean(self, tmp_path: Path) -> None:
        code = (
            "def run(cursor, user_id):\n"
            "    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))\n"
        )
        findings = scan_code(tmp_path, code)
        b101 = [f for f in findings if f.rule_id == "B101"]
        assert not b101, "Parameterised query should not trigger B101"

    def test_constant_string_in_execute_is_clean(self, tmp_path: Path) -> None:
        code = (
            "def run(cursor):\n"
            "    cursor.execute('SELECT 1')\n"
        )
        findings = scan_code(tmp_path, code)
        b101 = [f for f in findings if f.rule_id == "B101"]
        assert not b101, "Constant SQL should not trigger B101"


# ---------------------------------------------------------------------------
# B102 – Command Injection
# ---------------------------------------------------------------------------


class TestB102CommandInjection:
    def test_subprocess_run_shell_true_dynamic(self, tmp_path: Path) -> None:
        code = (
            "import subprocess\n"
            "def run(cmd):\n"
            "    subprocess.run(cmd, shell=True)\n"
        )
        findings = scan_code(tmp_path, code)
        b102 = [f for f in findings if f.rule_id == "B102"]
        assert b102, "Expected B102 for subprocess.run(cmd, shell=True)"
        assert b102[0].severity == "HIGH"

    def test_subprocess_popen_shell_true_dynamic(self, tmp_path: Path) -> None:
        code = (
            "import subprocess\n"
            "def run(user_cmd):\n"
            "    subprocess.Popen(user_cmd, shell=True)\n"
        )
        findings = scan_code(tmp_path, code)
        b102 = [f for f in findings if f.rule_id == "B102"]
        assert b102

    def test_os_system_dynamic(self, tmp_path: Path) -> None:
        code = (
            "import os\n"
            "def run(cmd):\n"
            "    os.system(cmd)\n"
        )
        findings = scan_code(tmp_path, code)
        b102 = [f for f in findings if f.rule_id == "B102"]
        assert b102, "Expected B102 for os.system(dynamic)"
        assert b102[0].severity == "HIGH"

    def test_subprocess_shell_false_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import subprocess\n"
            "def run(args):\n"
            "    subprocess.run(args, shell=False)\n"
        )
        findings = scan_code(tmp_path, code)
        b102 = [f for f in findings if f.rule_id == "B102"]
        assert not b102, "shell=False should not trigger B102"

    def test_subprocess_constant_cmd_shell_true_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import subprocess\n"
            "def run():\n"
            "    subprocess.run('ls -la', shell=True)\n"
        )
        findings = scan_code(tmp_path, code)
        b102 = [f for f in findings if f.rule_id == "B102"]
        assert not b102, "Constant command with shell=True is flagged by Bandit but we keep it clean"


# ---------------------------------------------------------------------------
# B103 – Path Traversal
# ---------------------------------------------------------------------------


class TestB103PathTraversal:
    def test_open_fstring_path(self, tmp_path: Path) -> None:
        code = (
            "def read(user_path):\n"
            "    with open(f'/data/{user_path}') as f:\n"
            "        return f.read()\n"
        )
        findings = scan_code(tmp_path, code)
        b103 = [f for f in findings if f.rule_id == "B103"]
        assert b103, "Expected B103 for open() with f-string path"
        assert b103[0].severity == "HIGH"

    def test_open_concatenated_path(self, tmp_path: Path) -> None:
        code = (
            "def read(filename):\n"
            "    with open('/uploads/' + filename) as f:\n"
            "        return f.read()\n"
        )
        findings = scan_code(tmp_path, code)
        b103 = [f for f in findings if f.rule_id == "B103"]
        assert b103, "Expected B103 for open() with + concatenation"

    def test_path_fstring(self, tmp_path: Path) -> None:
        code = (
            "from pathlib import Path\n"
            "def get(name):\n"
            "    return Path(f'/base/{name}')\n"
        )
        findings = scan_code(tmp_path, code)
        b103 = [f for f in findings if f.rule_id == "B103"]
        assert b103, "Expected B103 for Path() with f-string"

    def test_open_constant_path_is_clean(self, tmp_path: Path) -> None:
        code = (
            "def read():\n"
            "    with open('/etc/hosts') as f:\n"
            "        return f.read()\n"
        )
        findings = scan_code(tmp_path, code)
        b103 = [f for f in findings if f.rule_id == "B103"]
        assert not b103, "Constant path should not trigger B103"


# ---------------------------------------------------------------------------
# B201 – Hardcoded Secret
# ---------------------------------------------------------------------------


class TestB201HardcodedSecret:
    def test_password_assignment(self, tmp_path: Path) -> None:
        code = "password = 'SAST-TEST-DUMMY-VALUE'\n"
        findings = scan_code(tmp_path, code)
        b201 = [f for f in findings if f.rule_id == "B201"]
        assert b201, "Expected B201 for hardcoded password"
        assert b201[0].severity == "MEDIUM"

    def test_api_key_assignment(self, tmp_path: Path) -> None:
        code = "api_key = 'SAST-TEST-DUMMY-VALUE'\n"
        findings = scan_code(tmp_path, code)
        b201 = [f for f in findings if f.rule_id == "B201"]
        assert b201, "Expected B201 for hardcoded api_key"

    def test_token_annotation(self, tmp_path: Path) -> None:
        code = "auth_token: str = 'SAST-TEST-DUMMY-VALUE'\n"
        findings = scan_code(tmp_path, code)
        b201 = [f for f in findings if f.rule_id == "B201"]
        assert b201, "Expected B201 for hardcoded annotated token"

    def test_empty_string_ignored(self, tmp_path: Path) -> None:
        code = "password = ''\n"
        findings = scan_code(tmp_path, code)
        b201 = [f for f in findings if f.rule_id == "B201"]
        assert not b201, "Empty string should not trigger B201 (too trivial)"

    def test_env_lookup_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import os\n"
            "password = os.environ.get('PASSWORD')\n"
        )
        findings = scan_code(tmp_path, code)
        b201 = [f for f in findings if f.rule_id == "B201"]
        assert not b201, "Environment lookup should not trigger B201"


# ---------------------------------------------------------------------------
# B202 – Unsafe Deserialization
# ---------------------------------------------------------------------------


class TestB202UnsafeDeserialization:
    def test_pickle_loads(self, tmp_path: Path) -> None:
        code = (
            "import pickle\n"
            "def load(data):\n"
            "    return pickle.loads(data)\n"
        )
        findings = scan_code(tmp_path, code)
        b202 = [f for f in findings if f.rule_id == "B202"]
        assert b202, "Expected B202 for pickle.loads()"
        assert b202[0].severity == "HIGH"

    def test_yaml_load_no_loader(self, tmp_path: Path) -> None:
        code = (
            "import yaml\n"
            "def parse(s):\n"
            "    return yaml.load(s)\n"
        )
        findings = scan_code(tmp_path, code)
        b202 = [f for f in findings if f.rule_id == "B202"]
        assert b202, "Expected B202 for yaml.load() without Loader"
        assert b202[0].severity == "MEDIUM"

    def test_yaml_safe_load_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import yaml\n"
            "def parse(s):\n"
            "    return yaml.safe_load(s)\n"
        )
        findings = scan_code(tmp_path, code)
        b202 = [f for f in findings if f.rule_id == "B202"]
        assert not b202, "yaml.safe_load() should not trigger B202"

    def test_yaml_load_with_safe_loader_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import yaml\n"
            "def parse(s):\n"
            "    return yaml.load(s, Loader=yaml.SafeLoader)\n"
        )
        findings = scan_code(tmp_path, code)
        b202 = [f for f in findings if f.rule_id == "B202"]
        assert not b202, "yaml.load(Loader=SafeLoader) should not trigger B202"


# ---------------------------------------------------------------------------
# B203 – Weak Cryptographic Hash
# ---------------------------------------------------------------------------


class TestB203WeakCrypto:
    def test_hashlib_md5(self, tmp_path: Path) -> None:
        code = (
            "import hashlib\n"
            "def hash_it(s):\n"
            "    return hashlib.md5(s.encode()).hexdigest()\n"
        )
        findings = scan_code(tmp_path, code)
        b203 = [f for f in findings if f.rule_id == "B203"]
        assert b203, "Expected B203 for hashlib.md5()"
        assert b203[0].severity == "MEDIUM"

    def test_hashlib_sha1(self, tmp_path: Path) -> None:
        code = (
            "import hashlib\n"
            "def hash_it(s):\n"
            "    return hashlib.sha1(s.encode()).hexdigest()\n"
        )
        findings = scan_code(tmp_path, code)
        b203 = [f for f in findings if f.rule_id == "B203"]
        assert b203, "Expected B203 for hashlib.sha1()"

    def test_hashlib_sha256_is_clean(self, tmp_path: Path) -> None:
        code = (
            "import hashlib\n"
            "def hash_it(s):\n"
            "    return hashlib.sha256(s.encode()).hexdigest()\n"
        )
        findings = scan_code(tmp_path, code)
        b203 = [f for f in findings if f.rule_id == "B203"]
        assert not b203, "hashlib.sha256() should not trigger B203"


# ---------------------------------------------------------------------------
# Scanner structural tests
# ---------------------------------------------------------------------------


class TestScannerStructure:
    def test_finding_has_required_keys(self, tmp_path: Path) -> None:
        code = "password = 'SAST-TEST-DUMMY-VALUE'\n"
        findings = scan_code(tmp_path, code)
        assert findings
        f = findings[0]
        assert isinstance(f.file, str)
        assert isinstance(f.line_number, int) and f.line_number > 0
        assert isinstance(f.issue_description, str) and f.issue_description
        assert f.severity in ("HIGH", "MEDIUM", "LOW")
        assert isinstance(f.rule_id, str) and f.rule_id

    def test_finding_to_dict_has_required_keys(self, tmp_path: Path) -> None:
        code = "password = 'SAST-TEST-DUMMY-VALUE'\n"
        findings = scan_code(tmp_path, code)
        d = findings[0].to_dict()
        for key in ("file", "line_number", "issue_description", "severity"):
            assert key in d

    def test_syntax_error_file_is_skipped(self, tmp_path: Path) -> None:
        code = "def broken(:\n    pass\n"
        scanner = SecurityScanner()
        p = write_py(tmp_path, "broken.py", code)
        findings = scanner.scan_file(p, "broken.py")
        assert findings == [], "Unparseable files must be skipped without raising"

    def test_empty_file_produces_no_findings(self, tmp_path: Path) -> None:
        code = ""
        findings = scan_code(tmp_path, code)
        assert findings == []

    def test_multi_file_directory_scan(self, tmp_path: Path) -> None:
        write_py(tmp_path, "a.py", "password = 'SAST-TEST-DUMMY-VALUE'\n")
        write_py(tmp_path, "b.py", "import pickle\ndef f(d):\n    pickle.loads(d)\n")
        scanner = SecurityScanner()
        findings = scanner.scan_directory(tmp_path)
        rule_ids = {f.rule_id for f in findings}
        assert "B201" in rule_ids
        assert "B202" in rule_ids

    def test_focus_files_limits_scan(self, tmp_path: Path) -> None:
        write_py(tmp_path, "a.py", "password = 'SAST-TEST-DUMMY-VALUE'\n")
        write_py(tmp_path, "b.py", "x = 1\n")
        scanner = SecurityScanner()
        findings = scanner.scan_directory(tmp_path, focus_files=["b.py"])
        assert not findings, "Only b.py scanned; it has no findings"

    def test_venv_dir_is_excluded(self, tmp_path: Path) -> None:
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        write_py(venv, "secret.py", "password = 'SAST-TEST-DUMMY-VALUE'\n")
        scanner = SecurityScanner()
        findings = scanner.scan_directory(tmp_path)
        assert not findings, ".venv should be excluded from scan"


# ---------------------------------------------------------------------------
# Baseline comparison / delta tests
# ---------------------------------------------------------------------------


class TestBaselineComparison:
    def _scanner(self) -> SecurityScanner:
        return SecurityScanner()

    def test_no_new_findings_passes(self, tmp_path: Path) -> None:
        # Both baseline and post-patch have the same finding → passed=True
        finding = VulnerabilityFinding(
            file="auth.py", line_number=5, issue_description="test", severity="HIGH", rule_id="B201"
        )
        result = self._scanner().compare([finding], [finding])
        assert result.passed
        assert result.new_vulnerabilities == []

    def test_new_high_finding_fails(self, tmp_path: Path) -> None:
        existing = VulnerabilityFinding(
            file="auth.py", line_number=5, issue_description="old", severity="HIGH", rule_id="B201"
        )
        new_vuln = VulnerabilityFinding(
            file="auth.py", line_number=10, issue_description="new sql", severity="HIGH", rule_id="B101"
        )
        result = self._scanner().compare([existing], [existing, new_vuln])
        assert not result.passed
        assert len(result.new_vulnerabilities) == 1
        assert result.new_vulnerabilities[0].rule_id == "B101"

    def test_new_medium_finding_fails(self, tmp_path: Path) -> None:
        new_vuln = VulnerabilityFinding(
            file="utils.py", line_number=3, issue_description="md5 usage", severity="MEDIUM", rule_id="B203"
        )
        result = self._scanner().compare([], [new_vuln])
        assert not result.passed
        assert len(result.new_vulnerabilities) == 1

    def test_low_severity_does_not_fail(self, tmp_path: Path) -> None:
        low = VulnerabilityFinding(
            file="utils.py", line_number=3, issue_description="low risk", severity="LOW", rule_id="B999"
        )
        result = self._scanner().compare([], [low])
        assert result.passed, "LOW severity should not fail the security gate"
        assert result.new_vulnerabilities == []

    def test_pre_existing_finding_not_counted_as_new(self, tmp_path: Path) -> None:
        f = VulnerabilityFinding(
            file="auth.py", line_number=5, issue_description="pre-existing", severity="HIGH", rule_id="B101"
        )
        result = self._scanner().compare([f], [f])
        assert result.passed
        assert result.new_vulnerabilities == []

    def test_baseline_count_and_post_patch_count_correct(self) -> None:
        high1 = VulnerabilityFinding(
            file="a.py", line_number=1, issue_description="x", severity="HIGH", rule_id="B101"
        )
        high2 = VulnerabilityFinding(
            file="a.py", line_number=2, issue_description="y", severity="HIGH", rule_id="B102"
        )
        result = SecurityScanner().compare([high1], [high1, high2])
        assert result.baseline_count == 1
        assert result.post_patch_count == 2


# ---------------------------------------------------------------------------
# run_comparative_scan integration test
# ---------------------------------------------------------------------------


class TestComparativeScan:
    def test_clean_patch_passes(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        workspace = tmp_path / "workspace"
        source.mkdir()
        workspace.mkdir()
        write_py(source, "auth.py", "x = 1\n")
        write_py(workspace, "auth.py", "x = 2\n")  # trivial clean change
        scanner = SecurityScanner()
        result, elapsed = scanner.run_comparative_scan(
            source=source, workspace=workspace, changed_files=["auth.py"]
        )
        assert result.passed
        assert elapsed >= 0.0

    def test_vulnerability_introduced_fails(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        workspace = tmp_path / "workspace"
        source.mkdir()
        workspace.mkdir()
        write_py(source, "db.py", "def query(cursor):\n    cursor.execute('SELECT 1')\n")
        write_py(
            workspace,
            "db.py",
            "def query(cursor, user_id):\n    cursor.execute(f'SELECT * FROM t WHERE id={user_id}')\n",
        )
        scanner = SecurityScanner()
        result, _ = scanner.run_comparative_scan(
            source=source, workspace=workspace, changed_files=["db.py"]
        )
        assert not result.passed
        assert any(v.rule_id == "B101" for v in result.new_vulnerabilities)

    def test_error_in_scan_is_fail_open(self, tmp_path: Path) -> None:
        """Scanner errors must not hard-fail the pipeline (fail-open policy)."""
        scanner = SecurityScanner()
        result, _ = scanner.run_comparative_scan(
            source=tmp_path / "nonexistent_source",
            workspace=tmp_path / "nonexistent_workspace",
        )
        # Should not raise; may have an error message but passed=True (fail-open)
        assert isinstance(result, SecurityScanResult)


# ---------------------------------------------------------------------------
# Convenience function test
# ---------------------------------------------------------------------------


class TestRunSecurityScan:
    def test_module_level_helper_returns_result(self, tmp_path: Path) -> None:
        source = tmp_path / "s"
        ws = tmp_path / "w"
        source.mkdir()
        ws.mkdir()
        write_py(source, "f.py", "x = 1\n")
        write_py(ws, "f.py", "x = 1\n")
        result = run_security_scan(source=source, workspace=ws, changed_files=["f.py"])
        assert isinstance(result, SecurityScanResult)
        assert result.passed


# ---------------------------------------------------------------------------
# VulnerabilityFinding model tests
# ---------------------------------------------------------------------------


class TestVulnerabilityFindingModel:
    def test_fingerprint_is_stable(self) -> None:
        f = VulnerabilityFinding(
            file="auth.py", line_number=10, issue_description="x", severity="HIGH", rule_id="B101"
        )
        assert f.fingerprint() == "auth.py:10:B101"
        assert f.fingerprint() == f.fingerprint()

    def test_is_actionable_high_and_medium(self) -> None:
        high = VulnerabilityFinding(
            file="f.py", line_number=1, issue_description="x", severity="HIGH", rule_id="B101"
        )
        medium = VulnerabilityFinding(
            file="f.py", line_number=1, issue_description="x", severity="MEDIUM", rule_id="B201"
        )
        low = VulnerabilityFinding(
            file="f.py", line_number=1, issue_description="x", severity="LOW", rule_id="B999"
        )
        assert high.is_actionable()
        assert medium.is_actionable()
        assert not low.is_actionable()

