"""The plain-Portuguese action recognizer."""

import pytest

from app.telegram.intents import Intent, parse

NAMES = ["MacMaker", "tropa"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bloqueia o macmaker", Intent("lock_screen", "MacMaker")),
        ("trava a tela do tropa", Intent("lock_screen", "tropa")),
        ("Bloquear tela", Intent("lock_screen", None)),
        ("tira uma foto do MacMaker", Intent("webcam_photo", "MacMaker")),
        ("quero ver a câmera do tropa", Intent("webcam_photo", "tropa")),
        ("manda o relatorio.pdf do tropa", Intent("send_file", "tropa", "relatorio.pdf")),
        (
            "me envia notas finais.docx do MacMaker",
            Intent("send_file", "MacMaker", "notas finais.docx"),
        ),
        ("qual computador está mais quente?", None),
        ("o macmaker está bloqueado?", None),
        ("bom dia", None),
        ("manda um oi", None),
        ("/status", None),
    ],
)
def test_recognizer(text: str, expected: Intent | None) -> None:
    assert parse(text, NAMES) == expected
