#!/usr/bin/env python3
"""Confere, OFFLINE, se um token.json do Gmail e somente leitura (ADR-024).

Nao acessa a rede nem o Google: so le o arquivo token.json e mostra a conta (se houver) e os
escopos autorizados, com um veredito. Use antes de montar o token no servidor.

    python3 deploy/release/verificar-token-gmail.py /caminho/para/token.json

Sai com codigo 0 se o token for somente `gmail.readonly`; 1 caso contrario (ou arquivo invalido).
O backend tambem recusa, no ar, qualquer token que nao seja somente leitura (gmail_api.py).
"""

import json
import sys

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: verificar-token-gmail.py <token.json>", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"ERRO: arquivo nao encontrado: {path}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"ERRO: token.json invalido: {error}", file=sys.stderr)
        return 1

    account = data.get("account") or data.get("client_id", "")
    scopes = data.get("scopes")
    print(f"Arquivo : {path}")
    if account:
        print(f"Conta   : {account}")
    print(f"Escopos : {scopes if scopes else '(nenhum registrado)'}")

    if not isinstance(scopes, list) or not scopes:
        print(
            "\nVEREDITO: INDETERMINADO - o token nao registra escopos. "
            "Reautorize somente leitura com deploy/release/autorizar-gmail.py.",
            file=sys.stderr,
        )
        return 1
    extra = sorted({str(s) for s in scopes if s != READONLY_SCOPE})
    if extra:
        print("\nVEREDITO: NAO E SOMENTE LEITURA. Escopos alem de gmail.readonly:", file=sys.stderr)
        for scope in extra:
            print(f"  - {scope}", file=sys.stderr)
        print(
            "Esse token pode enviar/apagar e-mail. NAO use. Reautorize so com gmail.readonly "
            "(deploy/release/autorizar-gmail.py).",
            file=sys.stderr,
        )
        return 1
    print("\nVEREDITO: OK - somente leitura (gmail.readonly). Pode montar no servidor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
