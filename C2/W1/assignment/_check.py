import json
import os
import re
import sys

EXPECTED = ["create_train_val_dirs", "split_data", "train_val_generators", "create_model"]


def main():
    nb_path = os.path.join(os.path.dirname(__file__), "C2W1_Assignment.ipynb")
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    found = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        for m in re.finditer(r"#\s*GRADED\s+(?:FUNCTION|CLASS):\s*(\w+)", src):
            found.append(m.group(1))
    missing = [f for f in EXPECTED if f not in found]
    if missing:
        print(f"MISSING graded functions: {', '.join(missing)}")
        return 1
    print(f"OK  all {len(EXPECTED)} graded functions present: {', '.join(EXPECTED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
