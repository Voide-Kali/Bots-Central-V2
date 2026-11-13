"""The plain-Portuguese action recognizer."""

import pytest

from app.telegram.intents import Intent, parse

NAMES = ["MacMaker", "tropa"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # --- Lock screen (existing) ---
        ("bloqueia o macmaker", Intent("lock_screen", "MacMaker")),
        ("trava a tela do tropa", Intent("lock_screen", "tropa")),
        ("Bloquear tela", Intent("lock_screen", None)),
        ("tranca o tropa", Intent("lock_screen", "tropa")),
        # --- Lock screen (new natural phrases) ---
        ("protege meu macmaker", Intent("lock_screen", "MacMaker")),
        ("fecha a tela do tropa", Intent("lock_screen", "tropa")),
        # --- Photo (existing) ---
        ("tira uma foto do MacMaker", Intent("webcam_photo", "MacMaker")),
        ("quero ver a câmera do tropa", Intent("webcam_photo", "tropa")),
        # --- Photo (new natural phrases) ---
        ("mostra a camera do macmaker", Intent("webcam_photo", "MacMaker")),
        ("captura uma imagem do tropa", Intent("webcam_photo", "tropa")),
        ("deixa eu ver o macmaker", Intent("webcam_photo", "MacMaker")),
        # --- Send file (existing) ---
        ("manda o relatorio.pdf do tropa", Intent("send_file", "tropa", "relatorio.pdf")),
        (
            "me envia notas finais.docx do MacMaker",
            Intent("send_file", "MacMaker", "notas finais.docx"),
        ),
        # --- Send file (new natural phrases) ---
        ("pega o backup.zip do tropa", Intent("send_file", "tropa", "backup.zip")),
        ("busca o log.txt do macmaker", Intent("send_file", "MacMaker", "log.txt")),
        # --- Network scan (existing) ---
        ("scaneia a rede do tropa", Intent("network_scan", "tropa")),
        ("faz um scan de rede no MacMaker", Intent("network_scan", "MacMaker")),
        ("quem esta na minha rede", Intent("network_scan", None)),
        # --- Network scan (new natural phrases) ---
        ("mostra a rede do tropa", Intent("network_scan", "tropa")),
        ("quem ta conectado na rede", Intent("network_scan", None)),
        ("lista os dispositivos na rede do macmaker", Intent("network_scan", "MacMaker")),
        # --- Power (existing) ---
        ("suspende o macmaker", Intent("power", "MacMaker", "suspend")),
        ("Suspender o Mac Maker", Intent("power", None, "suspend")),
        ("reinicia o tropa", Intent("power", "tropa", "reboot")),
        ("desliga o macmaker", Intent("power", "MacMaker", "shutdown")),
        # --- Power (new natural phrases) ---
        ("coloca o macmaker pra dormir", Intent("power", "MacMaker", "suspend")),
        ("hiberna o tropa", Intent("power", "tropa", "suspend")),
        ("restarta o macmaker", Intent("power", "MacMaker", "reboot")),
        ("apaga o tropa", Intent("power", "tropa", "shutdown")),
        # --- Should NOT match (problems, questions, past tense) ---
        ("qual computador está mais quente?", None),
        ("o macmaker está bloqueado?", None),
        ("bom dia", None),
        ("o tropa travou de novo", None),
        ("meu macmaker está bloqueado", None),
        ("manda um oi", None),
        ("o tropa desligou sozinho", None),
        ("o macmaker está reiniciando", None),
        ("desliga a tela do tropa", None),
        ("/status", None),
    ],
)
def test_recognizer(text: str, expected: Intent | None) -> None:
    assert parse(text, NAMES) == expected
