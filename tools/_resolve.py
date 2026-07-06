"""CLI shim: print resolved data or output dir without quoting issues in bat."""
import sys
from src.paths import resolve_data_dir, resolve_out_dir

if __name__ == "__main__":
    print(resolve_data_dir() if sys.argv[1] == "data" else resolve_out_dir())