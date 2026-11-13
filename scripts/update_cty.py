"""Download the latest AD1C cty.dat into data/cty.dat.

Run before every contest:  python scripts/update_cty.py
"""
import urllib.request
from pathlib import Path

URL = "https://www.country-files.com/cty/cty.dat"
DEST = Path(__file__).resolve().parents[1] / "data" / "cty.dat"

if __name__ == "__main__":
    DEST.parent.mkdir(exist_ok=True)
    with urllib.request.urlopen(URL, timeout=30) as r:
        DEST.write_bytes(r.read())
    print(f"Saved {DEST} ({DEST.stat().st_size:,} bytes)")
