# Arquitetura

Monolito modular em Python/FastAPI com PostgreSQL, um agente em Go por dispositivo e duas
interfaces: o painel web (React) e o bot do Telegram. Nada fica exposto na internet: tudo
fala pela rede privada Tailscale.

```
 iPhone / Mac (navegador)        Telegram                 Mac / Kali (agente Go)
          | HTTPS                    | long polling (saida)         | HTTPS + JWS EdDSA
          v                          v                              v
   Caddy (*.ts.net) ------> FastAPI backend <---- bot (processo)   (heartbeat, comandos)
          | painel estatico         |                    |
          |                         v                    v
          |                    PostgreSQL <-------- Ollama (IA local, so leitura)
          |                         |
          +-------------------------+---> backup diario (HD)
```

## Componentes

| Componente | Onde | Responsabilidade |
|---|---|---|
| `backend/app/api` | FastAPI | Rotas HTTP versionadas (`/api/v1`), limites de corpo, origem, respostas genericas |
| `backend/app/auth` | | Cadastro, verificacao, login/sessoes, recuperacao de senha, identidade e heartbeat dos dispositivos, limites de abuso, HKDF (ADR-038) |
| `backend/app/devices` | | Telemetria, comandos aprovados (catalogo fechado: `send_file`, `lock_screen`, `unlock_screen`, `webcam_photo`, `network_scan`, `power`), localizacao de rede |
| `backend/app/telegram` | processo proprio | Bot: vinculo, comandos, alertas online/offline, resumo diario, alertas de recursos (CPU, disco, temperatura, bateria), entrega de arquivos |
| `backend/app/assistant` | | IA local somente leitura (Ollama) |
| `backend/app/audit` | | Trilha de auditoria append-only |
| `agent/` | Go, um por dispositivo | Identidade Ed25519, heartbeat assinado, telemetria, executor de comandos do catalogo, sensor de senha errada (opcional) |
| `frontend/` | React + Vite | Painel web same-origin |
| `deploy/server/` | Docker Compose | Stack do servidor de casa |

## Regras de fronteira

- So o backend (e o processo do bot, que e o mesmo codigo) acessa o PostgreSQL.
- O agente nunca recebe credencial de usuario; ele se autentica por assinatura com a propria
  chave em cada requisicao, com sequencia anti-replay compartilhada entre heartbeat e comandos.
- Acao sobre um computador so existe como **comando tipado**, criado pelo dono e aprovado por um
  segundo fator: o **PIN pessoal de 6 digitos** (ADR-016), armazenado como HMAC com subchave
  HKDF dedicada (ADR-038). O codigo por e-mail segue para cadastro e recuperacao de senha. Nao
  ha execucao de shell.
- A IA nao tem ferramentas: recebe um retrato de dados do proprio usuario e devolve texto.
- Toda acao relevante gera um evento de auditoria na mesma transacao.

## Banco de dados

25 migrations Alembic (0001 a 0025), cadeia integra. Modelos principais: `User`, `Session`,
`Device`, `DeviceTelemetry`, `DeviceCommand`, `AuditEvent`, `TelegramLink`, `ActionPin`.

## Decisoes

Ver `docs/ADR/` (ADR-001 a ADR-038). Destaques recentes:
- ADR-036: localizacao de rede opt-in
- ADR-038: separacao de chaves HMAC por HKDF (flag-day executado)
