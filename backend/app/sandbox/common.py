import shutil

MAX_OUTPUT_CHARS = 200_000

_IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
)
