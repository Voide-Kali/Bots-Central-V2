# Estado atual — Aval (repositório Bots-Central-V2)

Retrato do sistema na `main`. Atualize **só quando o estado mudar de verdade** (nova
capacidade, nova restrição, novo risco). O detalhe de cada mudança fica no PR e no git; o
diário antigo está em [HISTORY.md](HISTORY.md).

Última revisão: 2026-10-21.

## O que funciona

| Área | Situação | Referência |
|---|---|---|
| Conta | Cadastro, verificação de e-mail (código), login, sessões no servidor, refresh com rotação e detecção de replay, logout | [AUTH.md](AUTH.md), ADR-006/007/008 |
| Recuperação de senha | Código de 8 dígitos por e-mail; troca derruba sessões, Telegram e comandos abertos | ADR-014 |
| Dispositivos | Pareamento por token de uso único, identidade Ed25519, aprovação humana pelo fingerprint, heartbeat JWS EdDSA com anti-replay, online/offline | [DEVICE_ONLINE_V01.md](DEVICE_ONLINE_V01.md) |
| Telemetria | CPU/carga, memória, disco, temperatura (Linux), uptime dentro do heartbeat assinado; 7 dias de histórico | ADR-012 |
| Telegram | Vínculo por código, `/status`, `/historico`, alertas online/offline | [TELEGRAM.md](TELEGRAM.md), ADR-011 |
| IA local | Ollama, **somente leitura**, sem ferramentas, só os dados do próprio usuário | ADR-013 |
| Ação remota | `send_file`: pedido no Telegram → código no e-mail vinculado à ação → agente lê só a pasta compartilhada → bytes com hash assinado | ADR-015 |
| Auditoria | Append-only (trigger no PostgreSQL), mesma transação da ação, sem segredos | `app/audit` |
| Agente | Linux e macOS (Intel e Apple Silicon); instaladores com serviço | [agent/README.md](../agent/README.md) |
| Painel web | React: login, cadastro, recuperação, dispositivos, telemetria, vínculo do Telegram | ADR-009 |
| Servidor | Compose só no Tailscale, HTTPS `*.ts.net`, backup diário | [deploy/README.md](../deploy/README.md) |

## Validação

- CI em todo push/PR: backend (ruff, mypy, pytest com PostgreSQL 17, pip-audit), frontend
  (testes, lint, typecheck, build), agente (`go test -race`, `go vet`), gitleaks.
- Ponta a ponta local (2026-10-21): agente Go real ↔ backend real via HTTP — pareamento,
  heartbeat com telemetria, envio de arquivo com hash assinado, recusas (arquivo ausente, hard link).
- Agente testado num Mac real (Intel, 2026-10-21).

## Ainda não validado em produção

- Servidor de casa no ar (acesso pendente), Telegram e Gmail reais, Ollama real, instaladores
  no Mac e no Kali.

## Fora do escopo atual

App Flutter, acesso remoto (RustDesk), foto em senha errada, IA de e-mail, instalação de
programas, agente Windows, organizações com vários membros. Ver [ROADMAP.md](ROADMAP.md).

## Riscos conhecidos (aceitos nesta fase)

- O e-mail é a raiz de confiança: recupera a senha e aprova ações. A conta de e-mail precisa de 2FA.
- A aprovação é verificada no servidor; um servidor comprometido poderia aprovar sozinho.
  Mitigação futura: aprovação assinada no celular e verificada pelo agente.
- `ABUSE_CONTROL_HMAC_KEY` é reaproveitada (com domínios separados) para limites, reset e
  aprovação de comandos.
- Servidor e backup na mesma casa; Tailscale gratuito é para uso não comercial.
- Detalhes em [THREAT_MODEL.md](THREAT_MODEL.md) e nos ADRs.
