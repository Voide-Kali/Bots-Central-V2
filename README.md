# Aval (Bots Central V2)

**Aval** — *"uma IA que só age com o seu aval"*. Uma central para gerenciar os seus
próprios computadores pelo celular, com segurança em primeiro lugar: ver presença e
telemetria, receber alertas e executar ações remotas que **só acontecem depois de uma
aprovação humana**.

> Projeto de pesquisa do IFMS (Lucas Bittencourt / Voide). O nome do produto é **Aval**
> (decidido em 2026-10-21); o repositório continua como `Bots-Central-V2` até uma
> renomeação planejada.

## O princípio do "aval"

Nada perigoso acontece sem aprovação humana proporcional ao risco. Toda ação sobre um
computador existe apenas como **comando tipado** (catálogo fechado, sem execução de shell),
criado pelo dono e aprovado por um segundo fator — o **PIN pessoal de 6 dígitos** no
Telegram (ADR-016). A IA consulta e *propõe*, mas não age sozinha: ela não tem ferramentas,
não tem credenciais e nunca trata conteúdo externo como instrução.

## Arquitetura

Monólito modular em Python/FastAPI com PostgreSQL, um agente em Go por dispositivo e duas
interfaces (painel web React e bot do Telegram). Nada fica exposto na internet por padrão:
o acesso é pela rede privada **Tailscale**.

| Componente | Tecnologia | Responsabilidade |
|---|---|---|
| Backend | FastAPI + PostgreSQL | APIs versionadas (`/api/v1`), autenticação, sessões, identidade de dispositivos, telemetria, comandos aprovados, auditoria |
| Agente | Go, um por computador | Identidade Ed25519, heartbeat assinado (JWS EdDSA), telemetria e executor do catálogo de ações |
| Painel web | React + TypeScript + Vite | Login, cadastro, recuperação, dispositivos, telemetria (inclusive ao vivo), PIN, ações, vínculo do Telegram, aba Admin |
| Bot do Telegram | Processo do mesmo backend | Alertas online/offline, consultas, IA somente leitura, ações aprovadas por PIN |
| Landing / download | Site estático (`site/`) | Página pública de download dos instaladores (ADR-026/027/029) |

Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Início rápido (desenvolvimento)

Há um `compose.yaml` na raiz que sobe backend + banco (e, opcionalmente, o bot) localmente.

```bash
cp .env.example .env            # troque a senha de desenvolvimento
docker compose up --build       # sobe db, roda migrations e o backend na :8000
```

Verifique a saúde do backend:

```bash
curl http://localhost:8000/api/v1/health
```

Para subir também o bot do Telegram, preencha `TELEGRAM_BOT_TOKEN` e
`ABUSE_CONTROL_HMAC_KEY` no `.env` e use o profile:

```bash
docker compose --profile telegram up -d
```

Para trabalhar no backend em Python puro, a partir de `backend/`:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

## Testes

Rode antes de abrir um PR (ver [AGENTS.md](AGENTS.md)):

```bash
# Backend (PostgreSQL via scripts/test-db.sh)
cd backend && ruff check . && mypy app tests && pytest

# Frontend
cd frontend && npm test && npm run lint && npm run typecheck && npm run build

# Agente
cd agent && go test -race ./... && go vet ./...
```

A CI roda esses mesmos passos em todo push/PR, mais `pip-audit` e `gitleaks`.

## Deploy

O servidor de casa roda via Docker Compose na rede Tailscale (sem portas abertas na
internet; HTTPS `*.ts.net` pelo Caddy). O guia completo está em
[deploy/README.md](deploy/README.md): clona o código em `~/aval`, gera segredos com
`generate-env.sh`, sobe a stack (backend, bot, painel, backup diário cifrado) e pareia os
agentes. Há um `doctor.sh` para diagnóstico.

## Destaques de segurança

- **Aprovação de ação por PIN de 6 dígitos** (ADR-016): criado no painel com a senha da
  conta, guardado como HMAC; PINs óbvios recusados; 5 erros travam por 15 min. Código de
  8 dígitos por e-mail como alternativa quando não há PIN.
- **Identidade de dispositivo Ed25519**: chave gerada no aparelho, aprovada pelo dono via
  fingerprint; toda requisição é assinada (JWS EdDSA, audiência fixa por finalidade) com
  sequência anti-replay.
- **Catálogo fechado de ações** (`send_file`, `lock_screen`, `webcam_photo`,
  `network_scan`): backend assina um digest canônico e o agente só executa se bater, sem
  shell; cada agente opta explicitamente por cada ação.
- **Auditoria append-only** (trigger no PostgreSQL, mesma transação da ação, sem segredos).
- **Papel de banco de menor privilégio** para backend e bot (ADR-032).
- **Backups do banco cifrados com age** (ADR-033).
- **Acesso só pela rede Tailscale**; banco em rede Docker interna; same-origin (CORS
  desligado); senhas Argon2id e tokens persistidos só como digest.

Modelo completo em [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) e
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Relato de vulnerabilidades: [SECURITY.md](SECURITY.md).

## Documentação

Índice completo em [docs/README.md](docs/README.md). Comece por:

- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) — o que realmente funciona hoje.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — visão de componentes e fronteiras.
- [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) — princípios de segurança em vigor.
- [docs/ROADMAP.md](docs/ROADMAP.md) — plano de entrega e o que fica para depois.
- [docs/ADR/](docs/ADR/) — decisões de arquitetura registradas.

## Status

MVP em integração. Recursos como **app de celular (Flutter)**, **acesso remoto** e a
**IA de e-mail** são futuros (em roadmap ou em PR), **não estão na `main`**. O estado real,
com o que está validado e o que ainda não foi testado em produção, fica em
[docs/CURRENT_STATE.md](docs/CURRENT_STATE.md).

## Como contribuir

Leia [AGENTS.md](AGENTS.md) antes de qualquer mudança — ele vale para pessoas e IAs. Em
resumo: uma branch por tarefa a partir da `main` atual, sem emojis em código/docs/commits,
mudanças de arquitetura ou segurança exigem ADR, e todos os testes acima devem passar antes
do PR. Nenhuma IA aprova o próprio trabalho; o merge é sempre do responsável.
