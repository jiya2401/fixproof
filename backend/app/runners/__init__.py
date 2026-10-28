"""Multi-language test runner factory for FixProof.

Public API:
    get_language_runner(src_dir)  -> LanguageRunner
    detect_language(src_dir)      -> Language
    build_boundary_map(src_dir)   -> BoundaryMap
"""

from app.runners.base_runner import LanguageRunner
from app.runners.boundary import BoundaryMap, build_boundary_map
from app.runners.detector import Language, detect_language
from app.runners.go_runner import GoRunner
from app.runners.js_runner import JSRunner
from app.runners.python_runner import PythonRunner
from app.runners.schema import FailureDetail, TestRunResult


def get_language_runner(src_dir) -> LanguageRunner:
    """Factory: detect the project language and return the matching LanguageRunner.

    Parameters
    ----------
    src_dir:
        Path to the project source root (the directory containing ``go.mod``,
        ``package.json``, or Python source files).

    Returns
    -------
    LanguageRunner
        A concrete runner whose ``.language`` attribute reflects the detected
        language.
    """
    from pathlib import Path

    lang = detect_language(Path(src_dir))
    if lang == Language.GO:
        return GoRunner()
    if lang == Language.JS:
        return JSRunner()
    return PythonRunner()


__all__ = [
    "Language",
    "LanguageRunner",
    "BoundaryMap",
    "TestRunResult",
    "FailureDetail",
    "detect_language",
    "build_boundary_map",
    "get_language_runner",
    "PythonRunner",
    "JSRunner",
    "GoRunner",
]

