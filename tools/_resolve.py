"""CLI shim: print resolved data or output dir without quoting issues in bat."""
import sys
from pathlib import Path

# Ensure repo root is on sys.path so 'src' is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.paths import resolve_data_dir, resolve_out_dir

if __name__ == "__main__":
    print(resolve_data_dir() if sys.argv[1] == "data" else resolve_out_dir())