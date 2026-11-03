#!/usr/bin/env python3
"""Autoriza UMA vez o Gmail somente leitura e grava token.json (ADR-024).

Use isto quando voce NAO tem um token.json valido (ou o que tem nao e somente leitura). Roda o
fluxo de consentimento OAuth do Google pedindo apenas o escopo `gmail.readonly` e grava o
token.json que o servidor vai montar. E um passo manual, na SUA maquina, com navegador.

Pre-requisitos:
  1) Um OAuth client do tipo "Desktop app" no Google Cloud Console, baixado como credentials.json.
     (Google Cloud Console -> APIs e Servicos -> Credenciais -> Criar credenciais -> ID do cliente
      OAuth -> Aplicativo para computador. Ative a "Gmail API" no projeto.)
  2) As libs: pip install google-auth-oauthlib google-api-python-client

Uso:
  python3 deploy/release/autorizar-gmail.py --credentials credentials.json --out token.json

Depois: confira com verificar-token-gmail.py e copie o token.json para a pasta montada no servidor
(ex.: deploy/server/gmail/token.json). O escopo pedido e so leitura; o token nunca pode enviar,
apagar nem marcar e-mail.
"""

import argparse
import os
import sys

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Autoriza o Gmail somente leitura (gmail.readonly).")
    parser.add_argument("--credentials", required=True, help="credentials.json do OAuth client")
    parser.add_argument("--out", default="token.json", help="arquivo de saida (padrao: token.json)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="nao abrir navegador; mostra a URL para colar o codigo (maquina sem navegador)",
    )
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.credentials):
        print(f"ERRO: credentials.json nao encontrado: {args.credentials}", file=sys.stderr)
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "ERRO: faltam as libs. Instale com:\n"
            "  pip install google-auth-oauthlib google-api-python-client",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, [READONLY_SCOPE])
    if args.no_browser:
        creds = flow.run_console()
    else:
        creds = flow.run_local_server(port=0)

    # Grava com escopo gravado no arquivo, para o verificador e o servidor poderem conferir.
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.chmod(args.out, 0o600)
    print(f"OK: token somente leitura gravado em {args.out}")
    print("Confira com: python3 deploy/release/verificar-token-gmail.py " + args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
