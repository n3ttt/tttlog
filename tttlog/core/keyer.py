"""Voice and CW keyer: the parts that don't need audio devices or ports.

* PTT and CW commands for each radio dialect (see rig.py).
* Morse timing for keying a serial line (DTR/RTS) when the radio can't send
  CW text itself (Yaesu FTDX10: CAT has no "send this text" command).
* WAV files: where recordings live, and writing/reading 16-bit PCM.
"""
from __future__ import annotations

import re
import struct
import wave
from pathlib import Path

# -- PTT / CW over CAT --------------------------------------------------------
# PTT on/off. Kenwood "TX1" picks the rear/USB audio on TS-590/890 (TX0 = mic);
# Elecraft ignores the digit. Flex keys whatever the slice's TX audio source is
# (turn DAX on for the slice to send tttlog's audio).
PTT_ON = {"flex": b"ZZTX1;", "kenwood": b"TX1;", "yaesu": b"TX1;"}
PTT_OFF = {"flex": b"ZZTX0;", "kenwood": b"RX;", "yaesu": b"TX0;"}

# Radios whose CAT can send CW text ("KY text;", up to 24 characters a command).
CAT_CW = {"flex", "kenwood"}
KY_CHUNK = 24

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "/": "-..-.", "?": "..--..", ".": ".-.-.-", ",": "--..--", "=": "-...-", "+": ".-.-.",
    "-": "-....-",
}


def cw_text(text: str) -> str:
    """Upper-case, only characters a keyer can send, single spaces."""
    t = "".join(c for c in text.upper() if c in MORSE or c == " ")
    return re.sub(r" +", " ", t).strip()


# Cut numbers: letters sent in place of digits in the exchange (599 -> 5NN).
CUT_STYLES = {
    "none": "None (599)",
    "nt": "9 → N, 0 → T (5NN)",
    "ant": "1 → A, 9 → N, 0 → T",
    "all": "All: 1 A, 2 U, 3 V, 5 E, 7 B, 8 D, 9 N, 0 T",
}
_CUTS = {"none": {}, "nt": {"9": "N", "0": "T"}, "ant": {"1": "A", "9": "N", "0": "T"},
         "all": {"1": "A", "2": "U", "3": "V", "5": "E", "7": "B", "8": "D", "9": "N", "0": "T"}}


def cut_numbers(text: str, style: str, rst: bool = False) -> str:
    """Replace digits with cut letters. For an RST the first digit stays a number,
    so 599 is 5NN in every style (never 'ENN')."""
    table = _CUTS.get(style, {})
    if not table:
        return text
    if rst:
        t = text.strip()
        return t[:1] + "".join(table.get(c, c) for c in t[1:])
    return "".join(table.get(c, c) for c in text)


def cw_set_speed(wpm: int) -> bytes:
    return f"KS{max(5, min(60, int(wpm))):03d};".encode()


def cw_commands(dialect: str, text: str) -> list[bytes]:
    """CAT commands that make the radio send `text` as CW (empty if it can't)."""
    if dialect not in CAT_CW:
        return []
    chunks, cur = [], ""
    for word in cw_text(text).split(" "):
        while len(word) > KY_CHUNK - 1:             # a very long "word": split it hard
            if cur:
                chunks.append(cur + " "); cur = ""
            chunks.append(word[:KY_CHUNK - 1]); word = word[KY_CHUNK - 1:]
        piece = (" " if cur else "") + word
        if cur and len(cur) + len(piece) > KY_CHUNK - 1:    # leave room for the trailing space
            chunks.append(cur + " ")                # trailing space keeps the word gap
            cur = word
        else:
            cur += piece
    if cur:
        chunks.append(cur)
    return [f"KY {c};".encode() for c in chunks if c.strip()]


def cw_abort(dialect: str) -> list[bytes]:
    """Stop sending now: drop back to receive (clears the radio's CW buffer)."""
    return [PTT_OFF[dialect]] if dialect in PTT_OFF else []


# -- Morse timing (for keying a serial line) ----------------------------------
def morse_elements(text: str, wpm: int) -> list[tuple[bool, float]]:
    """(key down?, seconds) pairs. PARIS timing: a dit is 1.2 / wpm seconds."""
    dit = 1.2 / max(5, min(60, int(wpm)))
    out: list[tuple[bool, float]] = []

    def gap(units):
        if out and not out[-1][0]:
            out[-1] = (False, max(out[-1][1], units * dit))
        elif out:
            out.append((False, units * dit))

    for word_i, word in enumerate(cw_text(text).split(" ")):
        if word_i:
            gap(7)
        for ch_i, ch in enumerate(word):
            if ch_i:
                gap(3)
            for el_i, el in enumerate(MORSE[ch]):
                if el_i:
                    out.append((False, dit))
                out.append((True, dit if el == "." else 3 * dit))
    return out


def cw_seconds(text: str, wpm: int) -> float:
    return sum(s for _, s in morse_elements(text, wpm))


# -- WAV files ----------------------------------------------------------------
def wav_dir(config_dir: Path, mycall: str) -> Path:
    safe = re.sub(r"[^A-Z0-9]+", "_", (mycall or "NOCALL").upper()).strip("_") or "NOCALL"
    return config_dir / "wav" / safe


def safe_wav_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_")
    return f"{stem or 'message'}.wav"


def write_wav(path: Path, pcm16: bytes, rate: int, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)
    tmp.replace(path)


def read_wav(path: Path) -> tuple[bytes, int, int]:
    """(16-bit PCM, sample rate, channels). 8-bit and 24/32-bit files are converted."""
    with wave.open(str(path), "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        return raw, rate, ch
    if width == 1:
        return b"".join(struct.pack("<h", (b - 128) << 8) for b in raw), rate, ch
    if width in (3, 4):
        n = len(raw) // width
        return b"".join(raw[i * width + width - 2:i * width + width] for i in range(n)), rate, ch
    raise ValueError(f"unsupported WAV sample size: {width * 8} bits")


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        return 0.0


def float_to_pcm16(data: bytes) -> bytes:
    """32-bit float samples (what some Macs record in) -> 16-bit PCM."""
    n = len(data) // 4
    vals = struct.unpack(f"<{n}f", data[:n * 4])
    return struct.pack(f"<{n}h", *(max(-32768, min(32767, int(v * 32767))) for v in vals))


def peak(pcm16: bytes) -> float:
    """0..1 loudness of a chunk, for the recording level meter."""
    n = len(pcm16) // 2
    if not n:
        return 0.0
    vals = struct.unpack(f"<{n}h", pcm16[:n * 2])
    return max(abs(v) for v in vals) / 32768.0


def convert_pcm16(pcm: bytes, rate: int, ch: int, new_rate: int, new_ch: int) -> bytes:
    """Change sample rate / channel count of 16-bit PCM (simple, good enough for speech)."""
    n = len(pcm) // (2 * ch)
    frames = struct.unpack(f"<{n * ch}h", pcm[:n * ch * 2])
    mono = frames if ch == 1 else [sum(frames[i * ch:(i + 1) * ch]) // ch for i in range(n)]
    if new_rate != rate and n:
        m = max(1, int(n * new_rate / rate))
        step = rate / new_rate
        mono = [mono[min(n - 1, int(i * step))] for i in range(m)]
    if new_ch > 1:
        mono = [v for v in mono for _ in range(new_ch)]
    return struct.pack(f"<{len(mono)}h", *mono)
