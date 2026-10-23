"""Deterministic recognizer for action requests typed in plain Portuguese.

The owner can write "bloqueia o Mac" or "manda o relatorio.pdf do servidor"
instead of tapping a button. This module only reads the OWNER'S OWN MESSAGE
(never device data) and is plain pattern matching, not the language model:
the assistant still has no way to start an action (ADR-013), and every action
still needs the owner's PIN or e-mail code (ADR-016).
"""

import re
import unicodedata
from dataclasses import dataclass

# Commands only ("bloqueia", "trava", "tranca"); "travou" or "bloqueado" describe a
# problem and go to the assistant instead.
_LOCK = re.compile(r"\b(bloqueia|bloquear|bloqueie|trava|travar|trave|tranca|trancar|tranque)\b")
_PHOTO = re.compile(r"\b(foto\w*|webcam|camera)\b")
# Network scan: a scan verb, or "na (minha) rede" (e.g. "quem esta na minha rede").
_SCAN = re.compile(r"\b(scan\w*|escane\w*|escaneia|varre\w*|varredura)\b|\bna (minha )?rede\b")
_SEND = re.compile(r"\b(mand\w*|envi\w*|passa\w*|traz\w*|traga)\b")
_FILE = re.compile(r"^(.+?\.[a-z0-9]{1,8})(?![\w])", re.IGNORECASE)
_FILLER = {"me", "pra", "para", "mim", "o", "a", "os", "as", "um", "uma", "meu", "minha", "arquivo"}


@dataclass(frozen=True)
class Intent:
    kind: str  # catalogue action
    device_hint: str | None  # device name as written, if recognised
    argument: str = ""


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def find_device(text: str, names: list[str]) -> str | None:
    """The single device name mentioned in the text (longest match wins)."""
    folded = _fold(text)
    hits = [name for name in names if name and _fold(name) in folded]
    if not hits:
        return None
    hits.sort(key=len, reverse=True)
    return hits[0]


def parse(text: str, device_names: list[str]) -> Intent | None:
    if len(text) > 300 or text.strip().startswith("/") or "?" in text:
        return None  # questions go to the assistant
    folded = _fold(text)
    device = find_device(text, device_names)
    verb = _SEND.search(folded)
    if verb:
        # Folding keeps character positions for Portuguese text (accents are dropped
        # per character), so the original text can be sliced at the same offset.
        words = text[verb.end() :].split()
        while words and _fold(words[0]) in _FILLER:
            words.pop(0)
        match = _FILE.search(" ".join(words))
        if match:
            return Intent("send_file", device, match.group(1).strip())
    if _PHOTO.search(folded):
        return Intent("webcam_photo", device)
    if _LOCK.search(folded):
        return Intent("lock_screen", device)
    if _SCAN.search(folded):
        return Intent("network_scan", device)
    return None
