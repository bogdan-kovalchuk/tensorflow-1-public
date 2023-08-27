import json
import os
import re
import sys


class NotebookValidationError(ValueError):
    pass


def _expect_type(value, expected_type, location):
    if not isinstance(value, expected_type):
        raise NotebookValidationError(
            "{} must be {}, got {}".format(
                location, expected_type.__name__, type(value).__name__
            )
        )


def validate_notebook_structure(notebook):
    _expect_type(notebook, dict, "notebook")
    _expect_type(notebook.get("cells"), list, "cells")
    _expect_type(notebook.get("metadata"), dict, "metadata")
    _expect_type(notebook.get("nbformat"), int, "nbformat")
    _expect_type(notebook.get("nbformat_minor"), int, "nbformat_minor")
    if notebook["nbformat"] != 4:
        raise NotebookValidationError(
            "nbformat must be 4, got {}".format(notebook["nbformat"])
        )

    for index, cell in enumerate(notebook["cells"]):
        location = "cell {}".format(index)
        _expect_type(cell, dict, location)
        if cell.get("cell_type") not in {"code", "markdown", "raw"}:
            raise NotebookValidationError(
                "{} has unsupported cell_type: {}".format(
                    location, cell.get("cell_type")
                )
            )
        source = cell.get("source")
        if not isinstance(source, (str, list)):
            raise NotebookValidationError("{} source must be text or a list".format(location))
        if isinstance(source, list) and any(not isinstance(line, str) for line in source):
            raise NotebookValidationError("{} source contains a non-string item".format(location))
        _expect_type(cell.get("metadata"), dict, "{} metadata".format(location))
        if cell["cell_type"] == "code":
            _expect_type(cell.get("outputs"), list, "{} outputs".format(location))
            execution_count = cell.get("execution_count")
            if execution_count is not None and not isinstance(execution_count, int):
                raise NotebookValidationError(
                    "{} execution_count must be an integer or null".format(location)
                )
    return notebook


def load_notebook(nb_path):
    try:
        with open(nb_path, "r", encoding="utf-8") as notebook_file:
            notebook = json.load(notebook_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NotebookValidationError(str(error)) from error
    return validate_notebook_structure(notebook)


def find_notebooks(root):
    notebooks = []
    for dirpath, _, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.endswith(".ipynb") and not fn.startswith("."):
                notebooks.append(os.path.join(dirpath, fn))
    return sorted(notebooks)


def extract_graded_functions(nb_path):
    nb = load_notebook(nb_path)
    functions = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        for m in re.finditer(r"#\s*GRADED\s+(?:FUNCTION|CLASS):\s*(\w+)", src):
            functions.append(m.group(1))
    return functions


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    notebooks = find_notebooks(root)
    ok = 0
    fail = 0
    total_funcs = 0
    for nb_path in notebooks:
        rel = os.path.relpath(nb_path, root)
        try:
            load_notebook(nb_path)
            funcs = extract_graded_functions(nb_path)
            total_funcs += len(funcs)
            tag = f"  graded: {', '.join(funcs)}" if funcs else ""
            print(f"OK   {rel}{tag}")
            ok += 1
        except Exception as e:
            print(f"FAIL {rel}  {e}")
            fail += 1
    print(f"\n{ok} passed, {fail} failed, {total_funcs} graded functions found")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
