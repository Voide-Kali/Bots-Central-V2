# Arquitetura

Monólito modular em Python/FastAPI com PostgreSQL, um agente em Go por dispositivo e duas
interfaces: o painel web (React) e o bot do Telegram. Nada fica exposto na internet: tudo
fala pela rede privada Tailscale.

```
 iPhone / Mac (navegador)        Telegram                 Mac / Kali (agente Go)
          │ HTTPS                    │ long polling (saída)         │ HTTPS + JWS EdDSA
          ▼                          ▼                              ▼
   Caddy (*.ts.net) ──────► FastAPI backend ◄──── bot (processo)   (heartbeat, comandos)
          │ painel estático         │                    │
          │                         ▼                    ▼
          │                    PostgreSQL ◄──────── Ollama (IA local, só leitura)
          │                         │
          └─────────────────────────┴──► backup diário (HD)
```

## Componentes

| Componente | Onde | Responsabilidade |
|---|---|---|
| `backend/app/api` | FastAPI | Rotas HTTP versionadas (`/api/v1`), limites de corpo, origem, respostas genéricas |
| `backend/app/auth` | | Cadastro, verificação, login/sessões, recuperação de senha, identidade e heartbeat dos dispositivos, limites de abuso |
| `backend/app/devices` | | Telemetria e comandos aprovados (`send_file`) |
| `backend/app/telegram` | processo próprio | Bot: vínculo, comandos, alertas, entrega de arquivos |
| `backend/app/assistant` | | IA local somente leitura (Ollama) |
| `backend/app/audit` | | Trilha de auditoria append-only |
| `agent/` | Go, um por dispositivo | Identidade Ed25519, heartbeat assinado, telemetria, executor de comandos na pasta compartilhada |
| `frontend/` | React + Vite | Painel web same-origin |
| `deploy/server/` | Docker Compose | Stack do servidor de casa |

## Regras de fronteira

- Só o backend (e o processo do bot, que é o mesmo código) acessa o PostgreSQL.
- O agente nunca recebe credencial de usuário; ele se autentica por assinatura com a própria
  chave em cada requisição, com sequência anti-replay compartilhada entre heartbeat e comandos.
- Ação sobre um computador só existe como **comando tipado**, criado pelo dono e aprovado por um
  segundo fator (código no e-mail). Não há execução de shell.
- A IA não tem ferramentas: recebe um retrato de dados do próprio usuário e devolve texto.
- Toda ação relevante gera um evento de auditoria na mesma transação.

## Decisões

Ver `docs/ADR/` (ADR-001 a ADR-015). O ADR-010 (protocolo do agente, JWS EdDSA) foi aprovado
mas ainda não está versionado.
