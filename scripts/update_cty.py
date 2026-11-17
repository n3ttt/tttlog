"""Download the latest AD1C cty.dat into data/cty.dat.

Run before every contest:  python scripts/update_cty.py

The download is checked before it replaces anything: sites sometimes answer
with an error or "checking your browser" page instead of the file. If no good
copy can be had, an existing good data/cty.dat is kept (the build caches the
last good one), and only with no good copy at all does this fail.
"""
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tttlog.core.cty import CTY_URL, CtyDat  # noqa: E402

DEST = ROOT / "data" / "cty.dat"


def good(data: bytes) -> bool:
    try:
        CtyDat.check(data)
        return True
    except ValueError:
        return False


def fetch(tries: int = 3) -> bytes | None:
    req = urllib.request.Request(CTY_URL, headers={"User-Agent": "tttlog-build"})
    for n in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if good(data):
                return data
            print(f"try {n}: got {len(data):,} bytes that aren't a cty.dat "
                  f"(starts {data[:40]!r})", file=sys.stderr)
        except OSError as e:
            print(f"try {n}: {e}", file=sys.stderr)
        if n < tries:
            time.sleep(10 * n)
    return None


if __name__ == "__main__":
    DEST.parent.mkdir(exist_ok=True)
    data = fetch()
    if data:
        tmp = DEST.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(DEST)
        print(f"Saved {DEST} ({len(data):,} bytes)")
    elif DEST.exists() and good(DEST.read_bytes()):
        print(f"::warning::Couldn't download a fresh cty.dat; keeping the existing one "
              f"({DEST.stat().st_size:,} bytes)")
    else:
        DEST.unlink(missing_ok=True)
        sys.exit("No usable cty.dat: download failed and there's no good saved copy.")
