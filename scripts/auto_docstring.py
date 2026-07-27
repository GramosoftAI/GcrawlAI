"""
auto_docstring.py
Adds concise 1-line docstrings to every Python function/method
that currently has no docstring at all.
Run from the project root.
"""

import ast
import re
from pathlib import Path

TARGET_DIRS = ["api", "web_crawler", "scripts"]
SKIP_FILES = {"__init__.py", "celery_config.py", "auto_docstring.py"}


def snake_to_readable(name):
    name = re.sub(r"^_+", "", name)
    name = re.sub(r"_+", " ", name)
    return name.strip()


def infer_docstring(func_name):
    readable = snake_to_readable(func_name)
    if not readable:
        return "Execute this function."
    prefixes = {
        "get ": "Return ", "fetch ": "Fetch and return ", "load ": "Load ",
        "save ": "Save ", "create ": "Create ", "update ": "Update ",
        "delete ": "Delete ", "remove ": "Remove ", "insert ": "Insert ",
        "validate ": "Validate ", "verify ": "Verify ", "check ": "Check ",
        "run ": "Run ", "execute ": "Execute ", "handle ": "Handle ",
        "process ": "Process ", "reset ": "Reset ", "setup ": "Set up ",
        "send ": "Send ", "log ": "Log ", "parse ": "Parse ",
        "build ": "Build ", "compute ": "Compute ", "calculate ": "Calculate ",
        "increment ": "Increment ", "decrement ": "Decrement ", "set ": "Set ",
        "is ": "Return True if ", "has ": "Return True if the object has ",
        "init ": "Initialise ",
    }
    sentence = readable[0].upper() + readable[1:]
    for prefix, replacement in prefixes.items():
        if sentence.lower().startswith(prefix):
            sentence = replacement + sentence[len(prefix):]
            break
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def has_docstring(node):
    if not node.body:
        return False
    first = node.body[0]
    return isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant, ast.Str))


def add_docstrings_to_file(filepath):
    try:
        source = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  Could not read {filepath}: {e}")
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  Syntax error in {filepath}: {e}")
        return False

    lines = source.splitlines(keepends=True)
    insertions = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if has_docstring(node):
            continue
        func_name = node.name
        if func_name.startswith("__") and func_name.endswith("__"):
            if func_name not in ("__init__", "__call__", "__str__", "__repr__"):
                continue
        if not node.body:
            continue
        body_start_lineno = node.body[0].lineno
        body_line = lines[body_start_lineno - 1]
        indent = len(body_line) - len(body_line.lstrip())
        indent_str = " " * indent
        doc_text = infer_docstring(func_name)
        docstring_line = f'{indent_str}"""{doc_text}"""\n'
        insertions.append((body_start_lineno - 1, docstring_line))

    if not insertions:
        return False

    insertions.sort(key=lambda x: x[0], reverse=True)
    for line_idx, docstring_line in insertions:
        lines.insert(line_idx, docstring_line)

    try:
        filepath.write_text("".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"  Could not write {filepath}: {e}")
        return False


def main():
    root = Path(__file__).parent.parent
    total_files = 0
    modified_files = 0
    for target_dir in TARGET_DIRS:
        dir_path = root / target_dir
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            if py_file.name in SKIP_FILES:
                continue
            if "__pycache__" in py_file.parts:
                continue
            total_files += 1
            modified = add_docstrings_to_file(py_file)
            if modified:
                modified_files += 1
                print(f"  OK: {py_file.relative_to(root)}")
    print(f"\nDone. {modified_files}/{total_files} files updated.")


if __name__ == "__main__":
    main()
