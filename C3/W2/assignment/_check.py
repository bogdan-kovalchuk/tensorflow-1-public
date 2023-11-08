from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from notebook_check import assignment_main


if __name__ == "__main__":
    sys.exit(assignment_main(__file__))
