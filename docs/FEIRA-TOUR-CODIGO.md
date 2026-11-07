# Tour guiado do codigo (feira)

Para voce conseguir explicar qualquer parte do Aval e responder os avaliadores. Nao substitui os
docs tecnicos ([ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY_MODEL.md](SECURITY_MODEL.md),
[THREAT_MODEL.md](THREAT_MODEL.md)) nem os ADRs - resume e aponta onde cada coisa esta.

## Visao em uma frase

Um monolito modular em Python/FastAPI com PostgreSQL, um agente em Go por computador, e duas
interfaces (painel web React e bot do Telegram). Nada exposto na internet: o acesso e pela rede
privada Tailscale.

## Os quatro componentes e onde estao

| Componente | Linguagem | Pasta | Faz |
|---|---|---|---|
| Backend | Python/FastAPI | `backend/app` | APIs `/api/v1`, auth, identidade de dispositivos, telemetria, comandos aprovados, auditoria |
| Agente | Go | `agent/` | Identidade Ed25519, heartbeat assinado, telemetria, executor do catalogo de acoes |
| Painel web | React/TypeScript | `frontend/src` | Login, cadastro, dispositivos, telemetria ao vivo, PIN, acoes, Admin, Historico |
| Bot do Telegram | Python (mesmo backend) | `backend/app/telegram` | Alertas, consultas, IA so-leitura, aprovacao por PIN |

Fluxo de uma requisicao do agente: `agent/internal/transport/http.go` assina e envia ->
`backend/app/api/v1/routes/auth.py` (rotas de device) -> `backend/app/auth/device_online.py`
(regra de negocio) -> PostgreSQL.

## As camadas de seguranca (o coracao da pesquisa)

Cada item responde "por que a IA nao consegue agir sozinha nem ser manipulada".

### 1. Identidade do computador (Ed25519) e heartbeat assinado
- O agente gera uma chave no proprio aparelho e eu aprovo pelo fingerprint.
- Todo heartbeat e assinado (JWS EdDSA) com audiencia fixa e sequencia **anti-replay**.
- Onde: `agent/internal/identity/identity.go`, `agent/internal/jws/jws.go`; verificacao em
  `backend/app/auth/device_online.py`. ADR-003, ADR-012.

### 2. Catalogo fechado de acoes (sem shell)
- As acoes sao um conjunto fixo: `send_file`, `lock_screen`, `webcam_photo`, `network_scan`. Nao ha
  execucao de comando livre.
- O backend assina um **digest canonico** do comando; o agente so executa se o digest bater. Cada
  agente opta explicitamente por cada acao na instalacao (`AVAL_ACTIONS`).
- Onde: `backend/app/devices/commands.py`, `backend/app/api/v1/routes/device_actions.py`; no agente,
  o executor em `agent/internal`. ADR-016, ADR-015, ADR-020, ADR-021.

### 3. Aprovacao humana por segundo fator
- Acao de alto risco exige aprovacao: **PIN pessoal de 6 digitos** no Telegram, ou **codigo de 8
  digitos por e-mail** quando nao ha PIN.
- O PIN e guardado como **HMAC** (nunca em texto); PINs obvios sao recusados; 5 erros travam por 15
  min.
- Onde: `backend/app/auth/action_pin.py` (politica e HMAC), `backend/app/telegram/`. ADR-016, ADR-011.

### 4. Auditoria append-only
- Cada acao vira uma linha (quem, o que, quando, resultado). Um **gatilho no PostgreSQL** recusa
  UPDATE e DELETE: nem o sistema reescreve o historico.
- Onde: `backend/app/audit/events.py`; o gatilho na migration `0010_audit_events.py`. Visivel no
  painel (aba Historico) e por `GET /api/v1/audit`.

### 5. A IA que propoe, mas nao age
- A IA roda localmente (Ollama), **so leitura**. Nao tem ferramentas, nao tem credenciais, e trata
  todo conteudo externo como **dado, nunca instrucao**.
- Ela consulta telemetria e *sugere* - a execucao sempre passa pelas camadas 2 e 3.
- Onde: `backend/app/assistant/`, `backend/app/telegram/intents.py`. ADR-013, ADR-023.

### 6. Defesa em profundidade na infraestrutura
- **Menor privilegio no banco** (ADR-032): backend e bot conectam como `aval_app`, que so faz DML -
  nao e dono, nao mexe no schema nem no gatilho de auditoria.
- **Senha do dono fora dos processos expostos** (ADR-035): backend e telegram nao recebem a senha de
  superusuario do banco no ambiente.
- **Backups cifrados com age** (ADR-033): a chave privada fica fora do servidor.
- **Sem portas abertas** (ADR-030, ADR-031): acesso so via Tailscale; o Funnel termina o TLS.
- Senhas Argon2id; tokens guardados so como digest; CSP e same-origin no painel.

## Limites honestos (saiba dizer)

- Hoje o backend assina as acoes; **confio no servidor** para isso. A protecao contra um servidor
  comprometido - aprovacao assinada no celular e verificada pelo agente - esta no roadmap (adiada
  ate haver usuarios reais, ADR e principio de "seguranca proporcional" no ROADMAP).
- O painel e a API ficam expostos pela internet via Tailscale Funnel; esse risco foi **aceito e
  registrado** (ADR-030).
- Agente so para macOS e Linux; Windows e futuro.
- A chave HMAC e compartilhada entre quatro usos; separar por HKDF esta pendente (maior item tecnico
  aberto).

## Como o projeto se controla (processo)

- Uma branch por tarefa a partir da `main`; merge so com CI verde e revisao; **nenhuma IA aprova o
  proprio trabalho**; sem segredos em nenhuma IA. Ver `AGENTS.md`.
- Mudanca de arquitetura ou seguranca exige um **ADR** em `docs/ADR/`. Hoje sao 34 ADRs, cada um com
  o porque de uma decisao.
- CI roda testes de backend (PostgreSQL), frontend e do agente Go, mais `pip-audit` e `gitleaks`, em
  todo push.

## Mapa rapido para achar as coisas

- "Como um device entra?" -> `backend/app/auth/device_online.py` + `docs/DEVICE_ONLINE_V01.md`.
- "Como uma acao e aprovada?" -> `backend/app/auth/action_pin.py` + ADR-016.
- "Onde fica o modelo de seguranca?" -> `docs/SECURITY_MODEL.md` e `docs/THREAT_MODEL.md`.
- "O que realmente funciona hoje?" -> `docs/CURRENT_STATE.md`.
- "Por que tal decisao?" -> o ADR correspondente em `docs/ADR/`.
