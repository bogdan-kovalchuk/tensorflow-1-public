import json
import os
import re
import sys


def find_notebooks(root):
    notebooks = []
    for dirpath, _, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.endswith(".ipynb") and not fn.startswith("."):
                notebooks.append(os.path.join(dirpath, fn))
    return sorted(notebooks)


def extract_graded_functions(nb_path):
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
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
            with open(nb_path, "r", encoding="utf-8") as f:
                json.load(f)
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
