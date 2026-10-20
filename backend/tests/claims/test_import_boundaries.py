"""Import boundary test: app.rules must never import from app.claims.

This is a static AST check, not a runtime test.
"""

import ast
from pathlib import Path


def get_rules_package_dir() -> Path:
    """Find the app/rules package directory."""
    # Try within docker container first
    docker_path = Path("/app/app/rules")
    if docker_path.exists():
        return docker_path
    # Local path
    local_path = (Path(__file__).resolve().parents[3] / "backend" / "app" / "rules").resolve()
    if local_path.exists():
        return local_path
    # Fallback: find via importlib
    try:
        import app.rules
        return Path(app.rules.__file__).parent
    except ImportError:
        raise FileNotFoundError("Cannot locate app.rules package directory") from None


def collect_python_files(directory: Path) -> list[Path]:
    """Collect all .py files recursively."""
    return list(directory.rglob("*.py"))


def extract_imports(filepath: Path) -> list[str]:
    """Extract all module names from import statements in a Python file."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)

    return modules


def test_rules_has_no_import_of_claims():
    """app.rules must never import from app.claims (purity boundary)."""
    rules_dir = get_rules_package_dir()
    py_files = collect_python_files(rules_dir)

    violations: list[str] = []
    for py_file in py_files:
        imported = extract_imports(py_file)
        for mod in imported:
            if "app.claims" in mod or mod.startswith("claims"):
                violations.append(
                    f"{py_file.name}: imports {mod!r}"
                )

    assert not violations, (
        "BOUNDARY VIOLATION: app.rules imports app.claims:\n"
        + "\n".join(violations)
    )


def test_rules_has_no_import_of_db():
    """app.rules must have no database imports (purity: no DB, no network)."""
    rules_dir = get_rules_package_dir()
    py_files = collect_python_files(rules_dir)

    db_modules = {"sqlalchemy", "app.core.db", "app.models", "psycopg", "asyncpg"}
    violations: list[str] = []

    for py_file in py_files:
        imported = extract_imports(py_file)
        for mod in imported:
            for db_mod in db_modules:
                if mod == db_mod or mod.startswith(db_mod + "."):
                    violations.append(f"{py_file.name}: imports {mod!r}")

    assert not violations, (
        "PURITY VIOLATION: app.rules imports DB/ORM modules:\n"
        + "\n".join(violations)
    )


def test_rules_has_no_import_of_llm():
    """app.rules must not import any LLM/AI modules."""
    rules_dir = get_rules_package_dir()
    py_files = collect_python_files(rules_dir)

    llm_modules = {"openai", "anthropic", "google.generativeai", "app.llm"}
    violations: list[str] = []

    for py_file in py_files:
        imported = extract_imports(py_file)
        for mod in imported:
            for llm_mod in llm_modules:
                if mod == llm_mod or mod.startswith(llm_mod + "."):
                    violations.append(f"{py_file.name}: imports {mod!r}")

    assert not violations, (
        "PURITY VIOLATION: app.rules imports LLM modules:\n"
        + "\n".join(violations)
    )
