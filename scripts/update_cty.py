"""Download the latest cty.dat and MASTER.SCP into ~/.tttlog/data (same as Tools > Update country files)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tttlog.updater import update_data_files  # noqa: E402

if __name__ == "__main__":
    for line in update_data_files():
        print(line)
