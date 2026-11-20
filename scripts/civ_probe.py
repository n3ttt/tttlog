"""Find an Icom radio on this computer and read it over CI-V. Read-only: never transmits.

    python scripts/civ_probe.py            # try every USB serial port
    python scripts/civ_probe.py /dev/cu.usbserial-1110   # just this port

Prints each port, then for the one that answers: baud rate, CI-V address
(and so the model), frequency, mode, and whether DATA mode and CW-over-CI-V
work. Paste the output into the chat if anything looks wrong.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo  # noqa: E402

from tttlog.core import civ  # noqa: E402

BAUDS = [19200, 115200, 9600, 38400, 57600, 4800]
ADDRS = sorted({m[1] for m in civ.MODELS.values()})


def model_for(addr):
    names = [m[0] for k, m in civ.MODELS.items() if m[1] == addr and k != "other"]
    return " / ".join(names) or "unknown model"


def exchange(port, frames, wait=0.35):
    """Send frames, collect answers (bodies) for `wait` seconds."""
    port.readAll()
    for f in frames:
        port.write(f)
    port.flush()
    buf, end = b"", time.monotonic() + wait
    while time.monotonic() < end:
        port.waitForReadyRead(50)
        buf += bytes(port.readAll())
    got, _ = civ.split_frames(buf)
    return [g for g in got if len(g) >= 3 and g[1] != civ.CTRLID]   # drop our own echo


def probe(info):
    port = QSerialPort(info)
    if not port.open(QSerialPort.ReadWrite):
        print(f"   can't open ({port.errorString()}) - is tttlog or another program using it?")
        return False
    try:
        for baud in BAUDS:
            port.setBaudRate(baud)
            port.setDataTerminalReady(False)          # don't key a DTR keying line
            port.setRequestToSend(False)
            time.sleep(0.05)
            answers = exchange(port, [civ.frame(a, civ.C_RD_FREQ) for a in ADDRS])
            # also catch "transceive" broadcasts if someone's turning the dial
            radios = sorted({b[1] for b in answers if b[2] in (civ.C_RD_FREQ, civ.C_SND_FREQ)})
            if not radios:
                print(f"   {baud:>6} baud: no answer")
                continue
            for addr in radios:
                d = civ.IcomDialect(addr=addr, model=next((k for k, m in civ.MODELS.items()
                                                            if m[1] == addr), "other"))
                print(f"   {baud:>6} baud: ✓ Icom at CI-V address {addr:02X}h  ({model_for(addr)})")
                state = {}
                for _ in range(3):                        # freq, mode, data (a few tries)
                    for body in exchange(port, d.poll(), 0.4):
                        for kind, val in d.parse(body):
                            state[kind] = val
                    if "freq" in state and "mode" in state:
                        break
                print(f"          frequency {state.get('freq', '?')} kHz, mode {state.get('mode', '?')}")
                print(f"          DATA mode query: {'works' if d.data_ok else 'not supported'};"
                      f" CW text over CI-V: {'yes' if d.can_cw else 'no (use DTR/RTS keying)'}")
                print(f"\n   In tttlog: Config ▸ Radio ▸ Icom, model {model_for(addr)}, address {addr:02X},"
                      f" Serial / USB {info.portName()} at {baud} baud.")
            return True
        print("   no Icom answered. On the radio check CI-V Baud Rate (try 19200), and that the")
        print("   USB cable is the radio's USB port (not just power). Unplug/replug and try again.")
        return False
    finally:
        port.close()


def main():
    QCoreApplication(sys.argv)
    ports = QSerialPortInfo.availablePorts()
    want = sys.argv[1] if len(sys.argv) > 1 else None
    if sys.platform == "darwin":                           # cu.* is the one to use on a Mac
        ports = [p for p in ports if p.portName().startswith("cu.")]
    print("Serial ports:")
    for p in ports:
        print(f"  {p.systemLocation():40} {p.description()}  {p.manufacturer()}")
    if not ports:
        print("  none. Is the radio on and its USB cable plugged in? IC-7300 etc. use a Silicon Labs")
        print("  CP210x USB chip; macOS has a built-in driver for it (shows as cu.usbserial-…).")
        return 1
    found = False
    for p in ports:
        if want and want not in (p.systemLocation(), p.portName()):
            continue
        if not want and any(s in p.portName().lower() for s in ("bluetooth", "debug-console", "wlan")):
            continue
        print(f"\n{p.systemLocation()}  ({p.description() or '?'})")
        found = probe(p) or found
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
