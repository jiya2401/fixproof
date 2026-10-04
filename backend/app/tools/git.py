import subprocess
from pathlib import Path


def git_diff(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout
