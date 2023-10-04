import ast
import json
import os
import re
import sys


GRADED_MARKER = re.compile(
    r"#\s*GRADED\s+(?:FUNCTIONS?|CLASS):\s*([A-Za-z_]\w*)"
)


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


def cell_source(cell):
    source = cell.get("source", "")
    return source if isinstance(source, str) else "".join(source)


def extract_graded_functions_from_notebook(notebook):
    functions = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        functions.extend(GRADED_MARKER.findall(cell_source(cell)))
    return functions


def extract_definitions(notebook):
    definitions = {}
    for cell_index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse(cell_source(cell))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions.setdefault(node.name, []).append((cell_index, node))
    return definitions


def requires_notebook_runtime(source):
    for line in source.splitlines():
        if line.lstrip().startswith(("%", "!", "?")):
            return True
    return "get_ipython()" in source


def validate_code_syntax(notebook):
    errors = []
    skipped = []
    for cell_index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = cell_source(cell)
        if not source.strip():
            continue
        if requires_notebook_runtime(source):
            skipped.append(cell_index)
            continue
        try:
            ast.parse(source)
        except SyntaxError as error:
            errors.append(
                "cell {} line {}: {}".format(
                    cell_index, error.lineno or 0, error.msg
                )
            )
    return errors, skipped


def validate_metadata_hygiene(notebook):
    errors = []
    cell_ids = set()
    for cell_index, cell in enumerate(notebook["cells"]):
        cell_id = cell.get("id")
        if cell_id is not None:
            if not isinstance(cell_id, str) or not cell_id.strip():
                errors.append("cell {} has an invalid id".format(cell_index))
            elif cell_id in cell_ids:
                errors.append("cell {} has duplicate id {}".format(cell_index, cell_id))
            cell_ids.add(cell_id)
        tags = cell["metadata"].get("tags")
        if tags is not None and (
            not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)
        ):
            errors.append("cell {} metadata tags must be strings".format(cell_index))
    return errors


def validate_output_hygiene(notebook):
    errors = []
    output_count = 0
    executed_cells = 0
    allowed_output_types = {
        "display_data", "error", "execute_result", "stream", "update_display_data"
    }
    for cell_index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        if cell.get("execution_count") is not None:
            executed_cells += 1
        for output_index, output in enumerate(cell["outputs"]):
            output_count += 1
            location = "cell {} output {}".format(cell_index, output_index)
            if not isinstance(output, dict):
                errors.append("{} must be an object".format(location))
                continue
            output_type = output.get("output_type")
            if output_type not in allowed_output_types:
                errors.append("{} has invalid output_type {}".format(location, output_type))
            elif output_type == "error":
                errors.append(
                    "{} contains saved error {}".format(
                        location, output.get("ename", "without an exception name")
                    )
                )
            elif output_type == "stream" and output.get("name") not in {"stdout", "stderr"}:
                errors.append("{} has invalid stream name".format(location))
    return errors, output_count, executed_cells


def _definition_is_placeholder(node):
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            body = body[1:]
    if not body:
        return True
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Raise):
        exception = statement.exc
        if isinstance(exception, ast.Name):
            return exception.id == "NotImplementedError"
        if isinstance(exception, ast.Call) and isinstance(exception.func, ast.Name):
            return exception.func.id == "NotImplementedError"
    if isinstance(statement, ast.Return):
        return statement.value is None or (
            isinstance(statement.value, ast.Constant) and statement.value.value is None
        )
    return False


def validate_assignment(nb_path, expected):
    notebook = load_notebook(nb_path)
    expected = list(expected)
    errors = []
    if len(expected) != len(set(expected)):
        errors.append("expected function list contains duplicates")

    syntax_errors, _ = validate_code_syntax(notebook)
    errors.extend("syntax error: {}".format(error) for error in syntax_errors)
    errors.extend(validate_metadata_hygiene(notebook))
    output_errors, _, _ = validate_output_hygiene(notebook)
    errors.extend(output_errors)

    markers = extract_graded_functions_from_notebook(notebook)
    definitions = extract_definitions(notebook)
    missing_definitions = [name for name in expected if name not in definitions]
    if missing_definitions:
        errors.append("missing definitions: {}".format(", ".join(missing_definitions)))

    incomplete = []
    duplicated = []
    for name in expected:
        matches = definitions.get(name, [])
        if len(matches) > 1:
            duplicated.append(name)
        if matches and all(_definition_is_placeholder(node) for _, node in matches):
            incomplete.append(name)
    if duplicated:
        errors.append("duplicate definitions: {}".format(", ".join(duplicated)))
    if incomplete:
        errors.append("incomplete definitions: {}".format(", ".join(incomplete)))

    if markers:
        missing_markers = [name for name in expected if name not in markers]
        unexpected_markers = [name for name in markers if name not in expected]
        if missing_markers:
            errors.append("missing graded markers: {}".format(", ".join(missing_markers)))
        if unexpected_markers:
            errors.append("unexpected graded markers: {}".format(", ".join(unexpected_markers)))
    return errors


def find_notebooks(root):
    notebooks = []
    for dirpath, _, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.endswith(".ipynb") and not fn.startswith("."):
                notebooks.append(os.path.join(dirpath, fn))
    return sorted(notebooks)


def extract_graded_functions(nb_path):
    nb = load_notebook(nb_path)
    return extract_graded_functions_from_notebook(nb)


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    notebooks = find_notebooks(root)
    ok = 0
    fail = 0
    total_funcs = 0
    total_outputs = 0
    total_executed_cells = 0
    for nb_path in notebooks:
        rel = os.path.relpath(nb_path, root)
        try:
            notebook = load_notebook(nb_path)
            syntax_errors, skipped_cells = validate_code_syntax(notebook)
            metadata_errors = validate_metadata_hygiene(notebook)
            output_errors, output_count, executed_cells = validate_output_hygiene(notebook)
            validation_errors = syntax_errors + metadata_errors + output_errors
            if validation_errors:
                raise NotebookValidationError("; ".join(validation_errors))
            total_outputs += output_count
            total_executed_cells += executed_cells
            funcs = extract_graded_functions(nb_path)
            total_funcs += len(funcs)
            details = []
            if funcs:
                details.append("graded: {}".format(", ".join(funcs)))
            if skipped_cells:
                details.append("runtime cells skipped: {}".format(len(skipped_cells)))
            tag = "  " + "; ".join(details) if details else ""
            print(f"OK   {rel}{tag}")
            ok += 1
        except Exception as e:
            print(f"FAIL {rel}  {e}")
            fail += 1
    print(
        "\n{} passed, {} failed, {} graded functions found, "
        "{} outputs inspected across {} executed cells".format(
            ok, fail, total_funcs, total_outputs, total_executed_cells
        )
    )
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
