# Current State

## Envio de arquivo aprovado por e-mail v0.1 (2026-10-21, em revisão — exige aprovação)

- ADR-015: `/enviar` → código no e-mail vinculado à ação → `/aprovar` → agente busca o comando com JWS (sequência compartilhada com o heartbeat), lê só da pasta compartilhada (sem symlink, ≤ 10 MB) e devolve bytes com tamanho e SHA-256 assinados → bot entrega e apaga. Migration `0012_device_commands`. Instaladores criam a pasta compartilhada. Validação: backend PostgreSQL 16 completo verde; agente `go test -race` e `go vet` (linux e darwin); **teste ponta a ponta local com o agente Go real e o backend real via HTTP** (pareamento, heartbeat com telemetria, arquivo de 65 KB com hash conferido, erro `not_found`).

## Recuperação de senha v0.1 (2026-10-21, em revisão — exige aprovação)

- ADR-014: código de 8 dígitos por e-mail (15 min, uso único, só HMAC guardado, 5 tentativas), respostas genéricas, limites fail-closed, troca invalida todas as sessões (`security_version`). Migration `0011_password_reset`; tela `/recover` no painel. Validação local: backend PostgreSQL 16 `410 passed`; frontend 63 testes, lint, typecheck, build.

## Auditoria v0.1 (2026-10-21, em revisão)

- Tabela `audit_events` append-only (trigger PostgreSQL bloqueia UPDATE/DELETE; só `ON DELETE SET NULL` do usuário é permitido), migration `0010_audit_events`. Registrados na mesma transação da ação: login, pareamento criado/cancelado, enrollment, aprovação/rejeição de dispositivo, vínculo/desvínculo do Telegram. Detalhes nunca contêm segredos (chaves suspeitas são recusadas). Leitura: `GET /api/v1/audit` (só os próprios eventos) e `/historico` no Telegram. Validação local: PostgreSQL 16 `404 passed`.

## Assistente de IA local v0.1 (2026-10-21, em revisão)

- Texto livre no Telegram (chat vinculado) é respondido por um modelo local via Ollama com um snapshot somente leitura dos dispositivos do próprio usuário; sem ferramentas nem ações (ADR-013). Limite de 20 perguntas/10 min por chat. Validação local: backend com PostgreSQL 16 `397 passed`. Não testado contra um Ollama real.

## Bot do Telegram v0.1 (2026-10-21, em revisão)

- `python -m app.telegram.bot` (long polling, profile `telegram` no Compose), vínculo por código de uso único gerado no painel (`/api/v1/telegram/link-code`), `/status` com telemetria, `/desvincular`, alertas online/offline. Migration `0009_telegram_bot`. Ver [TELEGRAM.md](TELEGRAM.md). Validação local: backend com PostgreSQL 16 `392 passed`; frontend 61 testes, lint, typecheck, build. O loop do processo (`bot.py`) não tem teste automatizado; precisa de teste manual com token real.

## Telemetria v0.1 (2026-10-21, em revisão)

- Claim opcional `tel` no heartbeat assinado (ADR-012), migration `0008_device_telemetry`, retenção de 7 dias, `telemetry` em `GET /api/v1/devices` e histórico em `GET /api/v1/devices/{id}/telemetry`. Agente coleta CPU/carga/memória/disco/temperatura/uptime no Linux e no macOS (sem temperatura no macOS). Painel mostra a última amostra. Validação local: backend com PostgreSQL 16 `378 passed`; agente `go test -race`, `go vet` (linux e darwin); frontend 58 testes, lint, typecheck e build.

## MVP-1 hardening pending review (2026-09-17)

- The dedicated `review/mvp1-hardening` worktree adds PostgreSQL-backed pre-auth
  admission for anonymous enrollment, restores `User → Session` pairing lock order,
  adds server-side cancellation for unconsumed pairings, and makes web authenticated
  requests refresh-and-retry once after access-token expiry.
- Logout now prefers the HttpOnly refresh-cookie digest under the existing same-origin
  boundary, so it can revoke a server session after the in-memory access token expires.
- Validation results for this uncommitted review branch are recorded with the handoff,
  not asserted as an integrated MVP-1 release result.

## MVP-1 hardening follow-up (2026-09-19)

- Logout now treats a known refresh digest as authority for its owning session, including a
  consumed family member. Unknown or malformed refresh material is deliberately inert; only
  then may a supplied bearer revoke its own session. The public successful response remains
  `204`, and the existing same-origin boundary is unchanged.
- The web refresh/retry path now clears in-memory access authority only for an actual
  unauthenticated refresh rejection. Temporary backend and network failures continue as
  `ApiUnavailableError` and do not pretend that the cookie-backed session was invalidated.
- Pairing cancellation adds a durable `revoked_at` migration state and a PostgreSQL check
  preventing a pairing from being both consumed and revoked. The public pairing id is now
  required by the service DTO; cancellation remains scoped to the owner and initiating session.
- Final Unicode claim-validation gates passed: `ruff check .`; `mypy app tests` (52 files);
  focused PostgreSQL suite (53 passed); explicit Alembic `0006 → 0007 → 0006 → 0007`
  round-trip; full PostgreSQL suite (352 passed, 86% total coverage); `pip-audit` (no known
  vulnerabilities); frontend tests (56 passed), lint, typecheck, and build; and
  `git diff --check`. No commit or push was made.

## Repositório: remoção de `nvpn/` (2026-10-21)

- A pasta `nvpn/` (binário de ~78 MB commitado por engano) foi removida e adicionada ao `.gitignore`; o blob permanece no histórico Git.

## Dependências: correção do pip-audit (2026-10-21)

- PyJWT 2.15.1 (ambos os locks), urllib3 2.8.0 e certifi 2026.10.19 (`requirements.lock`); local em Python 3.13 sem PostgreSQL: ruff, mypy, `pip check` e pip-audit dos dois locks passaram; pytest `123 passed, 215 skipped`.

## MVP-1 E2E LIVE PASS (2026-09-13)

Local end-to-end validation passed using the dedicated PostgreSQL test container, Mailpit with
STARTTLS and verified local CA, loopback Caddy, and the Linux Agent `PC000`. The recorded public
outcomes were: register `202`; email verification `200`; login `200`; `auth/me` `200`; pairing
`201`; enrollment `201`; heartbeat while `PENDING` `403` (expected); explicit human approval
`200`; and heartbeat after approval `200`. The local Agent fingerprint matched the fingerprint displayed in Device
Center. Final Device Center state: `TOTAL 1`, `ONLINE 1`, `PENDENTES 0`, `PC000 ACTIVE / Online`.

No password, pairing or verification token, access/refresh token, private key, database URL, or
HMAC key was recorded. This supersedes earlier entries that marked the live E2E proof as pending.

## MVP-1 SMTP trust harness preparation (2026-09-12)

- O host tinha validado previamente o gate Backend PostgreSQL integrado em
  `334 passed`, `0 failed`, `0 skipped`, cobertura `86%`; esta execução não o
  repetiu porque não recebeu `TEST_DATABASE_URL` nem acesso não interativo ao
  `sudo docker` do host. A execução completa não-PostgreSQL neste ambiente
  excedeu a janela de comando antes de produzir resultado final, portanto não
  é registrada como aprovada.
- Backend recebeu `SMTP_CA_FILE` opcional. Ausente, mantém exatamente
  `ssl.create_default_context()` e as raízes do sistema. Presente, valida o
  PEM no startup e o adiciona com `load_verify_locations`, sem desativar
  hostname, `CERT_REQUIRED` ou STARTTLS. Testes focados de SMTP/configuração:
  `20 passed`; `ruff`, `mypy` e `pip check` passaram.
- O harness local em `scripts/e2e/` usa Mailpit `axllent/mailpit:v1.30.6`,
  gera CA/certificado temporários ignorados sob `.local/e2e-mailpit`, exige
  STARTTLS e publica SMTP/UI somente em `127.0.0.1`. A geração local confirmou
  CA → certificado e SAN `localhost`/`127.0.0.1`, com chaves `0600`; o script
  e helper também foram validados estaticamente. Pull/execução Docker requer
  `sudo` interativo e permanece **HOST PENDING**. Nenhuma raiz foi instalada
  no trust store do SO.
- Agent: `go test ./...`, `go test -race ./...` e `go vet ./...` passaram.
  Frontend: `npm test` passou em `47 tests`; lint, typecheck e build passaram.
  Uma primeira execução teve uma falha intermitente no teste Device Center de
  adapter de pairing (`46 passed, 1 failed`), mas a repetição isolada e a
  repetição completa passaram. Nenhum código Frontend foi alterado.
- O live E2E ainda não foi executado. Além do `sudo` necessário para Mailpit,
  o runbook agora inclui proxy Caddy local-only: Browser em
  `http://127.0.0.1:8080` para Vite/FastAPI same-origin e Agent em
  `https://localhost:8443` para FastAPI. O certificado HTTPS separado usa a
  CA local, com SAN `localhost`/`127.0.0.1`; teste Go 1.26 confirmou que ele
  falha sem CA e passa com `SSL_CERT_FILE` somente no processo, preservando
  hostname. Nenhum bypass CORS/TLS ou mudança de Agent foi adicionada. A prova
  Docker do proxy permanece **HOST PENDING**. Consulte [LOCAL_E2E.md](LOCAL_E2E.md).
  Sem commit, push, tag, deploy ou alteração de volume PostgreSQL.

## MVP-1 Device Online — integração controlada (2026-09-12)

- Base `41aa90d` em `mvp1/integration`; backup local
  `backup/mvp1-integration-pre-device-online` preserva essa base.
- Merges não fast-forward, na ordem Backend `d1e97cd` (`3d19aec`), Agent
  `e00bc7a` (`6edc50d`) e Frontend `44c3ea7` (`091b768`), sem squash.
- Somente `docs/CURRENT_STATE.md` conflitou nos merges Agent e Frontend; resolução
  manual preservou os três estados e corrigiu afirmações históricas obsoletas.
  Nenhum conflito de código. Diretórios Backend/Agent/Frontend permanecem idênticos
  aos respectivos checkpoints congelados; Infra e referências dos tracks inalteradas.
- Backend, usando a venv existente e `PYTHONPATH=.` a partir de `backend/`:
  gates direcionados `12 passed, 34 skipped`; suíte completa `119 passed,
  215 skipped, 0 failed`; cobertura parcial `58%`. `TEST_DATABASE_URL` ausente:
  gate PostgreSQL completo e cobertura com PostgreSQL são **HOST PENDING**.
  Nenhum limiar de cobertura encontrado na configuração versionada/CI.
  Ruff passou; mypy estrito passou em 52 arquivos com a configuração Backend.
  A execução ASGI sem progresso na sandbox foi interrompida; a repetição no host
  concluiu normalmente, sem alteração de código.
- Agent: `go test ./...`, `go test -race ./...` e `go vet ./...` passaram.
- Frontend: `npm ci` com lock existente; `npm test` passou em 47 testes;
  `npm run lint`, `npm run typecheck` e `npm run build` passaram.
- Auditoria estática: enrollment JSON em `POST /api/v1/devices/enrollments` com
  `pairing_token/public_key/proof/name/platform/agent_version`; heartbeat em
  `POST /api/v1/devices/{device_id}/heartbeat` com `{"jws":"..."}`; respostas
  `403 DEVICE_PENDING`, `403 DEVICE_REVOKED` e `409 STALE_HEARTBEAT` preservadas.
  `GET /api/v1/devices` mantém filtro pelo proprietário e `fingerprint: string | null`.
- Sem Telegram, Nmap, execução arbitrária de shell ou instalação remota de software;
  sem adapter mock no runtime Frontend, persistência de tokens em localStorage/
  sessionStorage ou persistência de pairing em texto puro (Backend guarda digest).
  Sem logging de chave privada e sem bearer no enrollment/heartbeat do Agent;
  assinatura continua EdDSA via `go-jose/v4`.
- Verificação de marcadores não encontrou conflitos pendentes; `git diff --check`
  passou. Live E2E Backend ↔ Agent ↔ Frontend permanece pendente e não foi executado.
  **READY FOR LIVE E2E: NO**, até fechar o gate PostgreSQL no host.
  Sem push, tags novas ou deployment; MVP-1 ainda não está completo.


## MVP-1 backend auth/devices

Backend integrado em `mvp1/integration` a partir do checkpoint `d1e97cd`.
The `mvp1/backend-auth-devices` track implements ACTIVE-account
login, PostgreSQL server-side sessions, opaque access and refresh tokens, refresh
rotation, family replay revocation, logout/revocation, `GET /api/v1/auth/me`, and
`GET /api/v1/devices` with ownership enforcement. The web-cookie endpoints enforce
same-origin Origin/CSRF checks. Access and refresh secrets are CSPRNG values; only
SHA-256 digests are persisted.

## Device Online V0.1 backend

Implemented on `device-online/backend-v0.1`: digest-only, one-time five-minute pairing;
Ed25519 proof-of-possession enrollment into `PENDING`; owner fingerprint approval/reject;
EdDSA-only JWS heartbeat with PostgreSQL conditional uint64 anti-replay; server-authoritative
`last_seen_at`; and derived 90-second ONLINE/OFFLINE presence. See [DEVICE_ONLINE_V01.md](DEVICE_ONLINE_V01.md).
Authenticated owner `GET /api/v1/devices` exposes `fingerprint: string | null`.
Agent checkpoint `e00bc7a` reconciliado com o contrato Backend congelado e Frontend
checkpoint `44c3ea7` com pairing/aprovação integrados em `mvp1/integration`.
Live E2E permanece pendente; MVP-1 não está completo. Infra permanece inalterada.
Remote actions e coleta invasiva estão fora do escopo.

Validação histórica do track auth/devices (anterior a Device Online): full backend suite `326 passed`, `0 failed`, coverage
`89%`; targeted MVP-1 authentication/HTTP/migration suite `38/38 passed`. Migration
`0004 ↔ 0005` round-trip passed against the dedicated `bots_central_test`
PostgreSQL database; Alembic head naquela validação era `0005_device_foundation`.
O head integrado atual é `0006_device_online_v01`. Validation includes
refresh concurrency and leakage regression using actual persisted access and
refresh digests. `ruff check .`, `mypy app tests`, `pip check`, `git diff --check`,
and `pip-audit -r requirements.lock --vulnerability-service osv` passed.

## Histórico: Fases 2B–3A — AUTH FOUNDATION + EMAIL DELIVERY

Os limites abaixo descrevem cada fase na época de sua entrega; o estado atual de
auth/sessões/tokens é o MVP-1 validado acima.

- Branch usada na Fase 3A: `phase/auth-http-delivery`.
- [AUTH.md](AUTH.md), [THREAT_MODEL.md](THREAT_MODEL.md), [ADR-006](ADR/ADR-006-authentication-session-strategy.md)
  e [ADR-007](ADR/ADR-007-reauthentication-security-gate.md) permanecem o desenho aprovado.
- As migrations `0002`–`0004` adicionam a fundação auth, challenges de verificação e
  buckets pseudonimizados de abuso; consulte [DATABASE.md](DATABASE.md) para relações,
  índices, invariantes e dados sensíveis.
- Na fundação de banco foram adicionados modelos SQLAlchemy, enums controlados e
  repositório de lookup por ID, e-mail canônico e digest. Naquela etapa ainda não
  havia emissão/verificação de tokens nem endpoint de auth; esses fluxos foram
  implementados posteriormente no MVP-1.
- A validação PostgreSQL real da Fase 2B.1 foi executada no banco dedicado
  `bots_central_test`; não foram criados endpoints ou fluxos de autenticação.
- A Fase 2B.2 adiciona apenas primitivas de senha: Argon2id com perfil explícito
  (`time_cost=3`, `memory_cost=65536` KiB, `parallelism=4`, `hash_len=32` e
  `salt_len=16`, `encoding=UTF-8`), validação de criação/alteração entre 15 e 1024
  caracteres Unicode e limite técnico máximo de 1024 também na verificação, sem
  mínimo nesta última para manter compatibilidade futura. Mismatch e `InvalidHashError`
  retornam `False`; `VerificationError` genérico torna-se `PasswordVerificationError`;
  `UnsupportedParametersError` e falhas inesperadas não são escondidos. A decisão de
  rehash não mascara hash corrompido. Consulte [PASSWORD_SECURITY.md](PASSWORD_SECURITY.md).
  Nenhuma senha em texto puro é persistida ou registrada. Login e endpoints ainda
  estavam ausentes na Fase 2B.2; o MVP-1 implementou login posteriormente.
- A Fase 2B.3 adiciona somente o serviço de domínio de registro. Ele valida e
  canonicaliza o e-mail, reutiliza Argon2id, e cria `User`, `UserEmail` principal não
  verificado e `PasswordCredential` em savepoint dentro da transação do chamador. A
  conta começa em `pending_verification`; nenhuma sessão, token, e-mail ou confirmação
  é criada. A unicidade de `email_canonical` no PostgreSQL permanece a autoridade e
  duplicidade é exposta internamente como `DuplicateEmailError`; a constraint
  `user_emails_email_canonical_key` foi confirmada no catálogo PostgreSQL. O serviço
  exige `Session` sem estado prévio `new`/`dirty`/`deleted`, para não fazer flush
  silencioso da unidade de trabalho do chamador antes do savepoint; o chamador mantém
  responsabilidade pela transação externa. Não foram criados endpoint HTTP, login,
  sessão/token operacional, envio/verificação de e-mail nem schema/migration novos.
  Consulte [REGISTRATION.md](REGISTRATION.md).
- A Fase 2B.4A aprovou o contrato de segurança de challenges de verificação de e-mail
  em [EMAIL_VERIFICATION.md](EMAIL_VERIFICATION.md) e ADR-008. A Fase 2B.4B implementa
  sua fundação: schema/model, migration `0003`, enums, geração e validação estrita de
  material, framing/HMAC-SHA-256 e keyring configurável. Issuance, resend, consume e
  transições de conta continuam fora desta etapa.
- A Fase 2B.4C implementa o serviço síncrono de staging de issuance/resend em
  `app/auth/email_verification_issuance.py`: locks PostgreSQL `UserEmail → User →
  Challenge`, relógio `clock_timestamp()` pós-lock, cooldown compartilhado de 60 segundos,
  supersede de siblings vivos e resultados plaintext efêmeros. A transação externa,
  commit e qualquer delivery permanecem responsabilidade do caller/fase futura.
- A Fase 2B.4D implementa `app/auth/email_verification_consume.py`: consume CODE/LINK,
  tentativas/exaustão commitáveis, confirmação do e-mail, ativação de conta pendente e
  invalidação de siblings vivos em uma transação. Mantém locks `UserEmail → User →
  Challenge`, reload autoritativo com `populate_existing=True` e um `clock_timestamp()`
  pós-lock. Caller controla commit/rollback externo; futura integração deve commitar
  antes de mapear/serializar HTTP ou executar I/O, inclusive para WrongCode e
  AttemptsExhausted. ACTIVE, LOCKED e DISABLED não são elegíveis. Não há schema novo,
  migration, endpoint HTTP, delivery, login ou criação de sessão/token nesta fase.
- A Fase 2B.4E implementa `email_verification_application` e
  `email_verification_delivery`: a application layer possui a transação externa por
  session factory, compõe registro+issuance atomicamente e commita outcomes normais de
  consume antes de transporte futuro. DeliveryIntent é DTO ORM/Session-free, efêmero e
  redigido; dispatcher faz uma tentativa best-effort sem retry. Não há HTTP/provider,
  BackgroundTasks, fila/outbox, persistence de delivery, migration ou rate-limit.
- A Fase 3A expõe a foundation HTTP anônima de registration, resend e consume CODE/LINK;
  `AuthHttpRuntime` preserva a application layer como dona da transação. Há limiter
  PostgreSQL compartilhado e fail-closed, com chaves HMAC pseudonimizadas separadas,
  política de IP/rede confiável e guarda local de concorrência para Argon2. A entrega
  SMTP STARTTLS é configurável e ocorre uma vez em `BackgroundTasks` somente depois do
  corpo da resposta; em produção SMTP e `PUBLIC_ORIGIN` HTTPS são obrigatórios no startup.
  Em produção `ABUSE_CONTROL_HMAC_KEY` também é obrigatório e independente. O entrypoint
  mantém Uvicorn `--no-proxy-headers`; o proxy confiável deve enviar exatamente um XFF,
  sem suporte a cadeias multi-hop.
  Consume expõe somente sucesso verificado ou falha genérica, após a application layer
  commitar outcomes mutáveis. Não há Redis, outbox, retry automático ou garantia de entrega.

## Current implemented

- Backend foundation e auth database foundation.
- Modelos `User`, `UserEmail` e `PasswordCredential`.
- Segurança de senha Argon2id, canonicalização de e-mail e serviço interno de registro.
- Criação de conta `pending_verification` com e-mail principal não verificado.
- Fundação persistente de `email_verification_challenges`: enums, modelo SQLAlchemy,
  migration `0003`, constraints materiais/terminais e índices PostgreSQL.
- Primitivas de material: token de link de 32 bytes/CSPRNG com base64url canônico e
  digest SHA-256 dos bytes; código ASCII de oito dígitos, framing HMAC canônico,
  HMAC-SHA-256 e comparação constant-time.
- Keyring HMAC externo versionado, com segredo base64url de no mínimo 256 bits,
  carregado e validado somente quando o componente é instanciado, sem default.
- Serviços internos de issuance/resend de LINK e CODE separados do transporte HTTP
  e delivery; testes de PostgreSQL real incluem rollback, cooldown, siblings e concorrência.
- Consume de CODE/LINK com precedência de estados, attempts_exhausted, verified_at,
  pending_verification → active e siblings vivos invalidados por email_already_verified.
  Retry consumido é idempotente; versão HMAC desconhecida falha fechada sem mutação.
- Orchestration interna de registro/resend/consume e foundation de dispatch pós-commit
  com DeliveryIntent puro; a Fase 3A adiciona somente as rotas anônimas de e-mail.
- Rotas públicas JSON: `POST /api/v1/auth/register`,
  `POST /api/v1/auth/email-verification/resend`,
  `POST /api/v1/auth/email-verification/consume-code` e
  `POST /api/v1/auth/email-verification/consume-link`; `GET /email-verification` é uma
  página própria inerte que lê token somente do fragmento e exige POST explícito.
- Limiter PostgreSQL em `auth_abuse_buckets`, `PUBLIC_ORIGIN` tipada e adapter SMTP
  STARTTLS configurável. CORS permanece desabilitado para a topologia same-origin.
- MVP-1: login de contas ACTIVE e sessões server-side em PostgreSQL; access/refresh
  opacos, persistência somente de digests, refresh rotation, revogação por replay e
  logout com revogação de sessão/tokens.
- `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh` e
  `POST /api/v1/auth/logout` com Origin/CSRF na boundary web same-origin;
  `GET /api/v1/auth/me` autenticado e `GET /api/v1/devices` restrito ao proprietário.
- Migration `0005_device_foundation` e lifecycle de devices separados de presence.
  A migration `0006_device_online_v01` adiciona pairing, identidade e presence real.
- O Agent Linux possui a implementação local de Device Online V0.1 reconciliada com o
  contrato congelado de Backend: identidade Ed25519 local, fingerprint canônico `SHA256:`,
  enrollment JSON/PoP, JWS `EdDSA` via `go-jose/v4`, sequência `uint64` durável/monotônica,
  probes PENDING, tratamento fail-closed de stale/revogação e transporte HTTPS sem redirects.
  O agente não implementa remote commands, token permanente de usuário ou API key estática.
- Frontend Device Online v0.1 integrado do track `device-online/frontend-v0.1`,
  com contrato Backend congelado
  em `d1e97cd` e Agent em `e00bc7a`. Não houve mudança de arquitetura.
- O cliente HTTP same-origin implementa list/createPairing/approve/reject; `fingerprint`
  é obrigatório e aceita `null` para dispositivos sem chave Device Online. A UI exibe
  o fingerprint completo e exige comparação exata com o Agent; fingerprint nulo em
  dispositivo pendente bloqueia decisões. Rejeição exige confirmação explícita.
- Pairing token existe somente em estado React, com cópia explícita e validade exibida;
  cancelamento, expiração, decisão concluída e saída da sessão removem o estado. Respostas
  de criação recebidas após logout/unmount são descartadas. Não há persistência, URL,
  log de segredo ou mock no runtime.
- Consultas de dispositivos são serializadas; polling de cinco segundos existe somente
  enquanto o pairing está aberto, pula consultas em andamento e limpa timers ao terminar
  ou desmontar. Decisões sempre provocam nova consulta após a resposta, inclusive se uma
  consulta anterior ainda estiver em andamento. Lifecycle/presença/last_seen continuam
  exclusivamente derivados do Backend, sem transições otimistas ou heartbeat simulado.
- Access token continua em memória e refresh usa cookie HttpOnly: 401 limpa token/sessão;
  403 preserva token/sessão e mantém `ForbiddenError` tipado. Visual, navegação e estilos
  responsivos existentes foram reutilizados.
- Validação frontend desta conclusão: `npm test` (47 testes), `npm run lint`,
  `npm run typecheck`, `npm run build` e `git diff --check`. Auditoria de runtime exclui
  testes e não encontra mocks nem armazenamento de segredos. Integração HTTP validada
  com fetch controlado em testes e inspeção do contrato congelado; fluxo real com
  Backend/Agent em execução não foi exercitado nesta etapa.

## Design approved

- Contrato operacional de email verification da Fase 2B.4A, incluindo key rotation,
  concorrência, retenção, locks, issuance/resend e consume; operação da rotação de
  chaves HMAC e retenção de email verification permanecem futuras.

## Pending integration / Not implemented

- Live E2E Backend ↔ Agent ↔ Frontend permanece pendente; MVP-1 não está completo.
- Remote actions, Security Gate completo e Task Engine futuro permanecem fora deste MVP-1.
- Recovery, auditoria durável, verificação de e-mail secundário em ACTIVE e
  suporte CORS cross-origin aprovado permanecem pendentes.
- Mobile e contrato de refresh para clientes nativos permanecem futuros.
- O Agent somente persiste `active` após um probe heartbeat assinado ser aceito pelo Backend.

## Validated locally:

- A aplicação FastAPI inicia e expõe `GET /api/v1/health` via transporte ASGI público.
- A configuração tipada rejeita URL inválida e debug em produção.
- Health retorna JSON com estado `ok`/`connected` ou `degraded`/`unavailable`.
- Logging redige password, token, Authorization, API key e URL PostgreSQL com senha.
- Alembic gera SQL para a migration inicial sem tabelas de produto.
- Docker Compose `2.40.3-3` e o daemon Docker foram validados neste ambiente.
- O build Docker sem cache passou usando o lock exclusivo de runtime.
- PostgreSQL real ficou healthy; a migration `0001_foundation`, `SELECT 1` e o health
  HTTP real retornaram banco `connected`.
- O container do backend executou como `uid=100(app)`, sem privilégios de root.
- `pip-audit -r requirements.runtime.lock` passou sem vulnerabilidades conhecidas.
- A rede Compose usa MTU `1400` neste host.
- PostgreSQL 17 em container ficou healthy para a validação da Fase 2B.1.
- A migration `0002_auth_database_foundation` executou upgrade real, downgrade para
  `0001_foundation` e novo upgrade real com sucesso.
- Os constraints, lookup de digest e isolamento por savepoint foram validados contra
  PostgreSQL real no banco dedicado `bots_central_test`.
- O mapeamento SQLAlchemy dos enums persistidos usa `.value`, compatível com os labels
  PostgreSQL lowercase da migration; os roundtrips reais de `AccountStatus`,
  `AuthenticationLevel` e `SessionRevocationReason` passaram.
- `ruff check .`, `mypy app tests` e `python -m pip check` passaram após a correção de enums.
- `pytest` com `TEST_DATABASE_URL` real passou com `19 passed`, `0 skipped` e cobertura total
  de `92%`.
- `alembic upgrade head --sql` gerou DDL PostgreSQL para `0002_auth_database_foundation`.
- A validação final da Fase 2B.2 executou a suíte completa contra PostgreSQL 17 real,
  exclusivamente no banco dedicado `bots_central_test`: `42 passed`, `0 skipped`,
  `0 failed`, `0 errors` e cobertura total de `93%`; `app/auth/passwords.py` atingiu
  100% de cobertura. Não há senha de banco nem URL de teste registrada aqui.
- A validação final da Fase 2B.3 executou a suíte completa contra PostgreSQL 17 real,
  exclusivamente no banco dedicado `bots_central_test`: `58 passed`, `0 skipped`,
  `0 failed`, `0 errors` e cobertura total de `93%`. `app/auth/registration.py`
  atingiu 95% de cobertura e `app/auth/passwords.py`, 100%. Não há senha de banco nem
  URL de teste registrada aqui.
- A validação da Fase 2B.4C executou a suíte completa contra PostgreSQL 17 real,
  exclusivamente no banco dedicado `bots_central_test`: `142 passed`, `0 skipped`,
  `0 failed`, `0 errors` e cobertura total de `93%`. A migration `base -> head`, o
  catálogo PostgreSQL de constraints/índices/enums, a matriz de NULL/três valores e a
  configuração do keyring por ambiente foram cobertos por testes de regressão. A suíte
  também cobre issuance/resend 2B.4C em PostgreSQL real, incluindo cooldown, rollback,
  siblings vivos e duas transações concorrentes. Não há senha de banco, URL de teste ou
  segredo operacional registrado aqui.
- A validação corrente da Fase 2B.4E usou PostgreSQL 17.11 real no banco dedicado
  `bots_central_test`: application `19 passed`; suíte completa `241 passed`, `0 skipped`,
  `0 failed`, `0 errors`. Cobertura total `94%`; application `98%` e delivery `100%`.
  Os testes incluem composição atômica registro+issuance, ausência de commit intermediário,
  rollback/commit externo, intents pós-commit ORM/Session-free redigidos, outcomes mutáveis
  de consume commitados e dispatch de tentativa única sanitizada. A cobertura preexistente
  de consume mantém serialização PostgreSQL real, locator obsoleto, identity map e
  commit/rollback de tentativas. `ruff check .`, `mypy app tests`, `pip check` e
  `git diff --check` passaram. `pip-audit --vulnerability-service osv` passou sem
  vulnerabilidades conhecidas; a consulta padrão ao PyPI havia falhado por reset de conexão,
  portanto OSV foi a alternativa efetivamente validada.
- A validação corrente da Fase 3A usou PostgreSQL 17.11 real no banco dedicado
  `bots_central_test`: foundation HTTP/limiter `52 passed`; suíte completa `288 passed`,
  `0 skipped`, `0 failed`, `0 errors`. Cobertura total `89%`; route auth `80%`, limiter
  `88%` e delivery `78%`. A matriz cobre migration `0004`, concorrência PostgreSQL,
  expiração/cleanup de buckets, admission antes de Argon2, respostas genéricas,
  commits de consume, distinção pública entre sucesso verificado e falha genérica,
  body caps, página LINK inerte, headers, dispatch após corpo ASGI, SMTP fake STARTTLS,
  startup SMTP/abuse-control obrigatório em produção, peer/XFF trusted-proxy fail-closed
  e entrypoint Uvicorn sem proxy-header parsing. `ruff check .`, `mypy app tests`, `pip check`
  e `git diff --check` passaram. `pip-audit --vulnerability-service osv` passou sem
  vulnerabilidades conhecidas, sem registrar segredos ou URLs de banco.

## Not validated:

- Gitleaks local permanece pendente; o scanner continua configurado no CI.
- Recovery, Security Gate completo, Task Engine e ações remotas
  ainda não têm implementação operacional para validar. Emissão/rotação de tokens,
  revogação por replay e logout/revogação já foram validados no MVP-1.

## Pendências conhecidas:

- Gitleaks local continua pendente de instalação/execução.
- Operação das chaves HMAC, retenção e critérios de recuperação sem e-mail
  permanecem pendentes para os respectivos fluxos futuros; login, sessões,
  tokens e revogação do MVP-1 já estão implementados e validados.
- A validação HTTP end-to-end do Agent contra uma instância Backend com PostgreSQL permanece
  pendente; os testes locais cobrem o contrato congelado com transporte hermético.
- Prova reforçada e consentimento para poderes remotos permanecem indefinidos;
  a política proposta mantém essas ações negadas até decisão específica.

## Funcionando

- Compose define serviços separados para banco, migration one-shot e backend.
- O backend no Dockerfile executa como usuário não privilegiado `app`.
- `requirements.lock` fixa o conjunto de dependências validado para instalação e CI.
- `requirements.runtime.lock` fixa somente as dependências externas do container.
- FastAPI `0.141.1` resolve Starlette `1.6.0` sem pin direto.
- MTU `1400` foi necessário neste host por um problema de PMTU/bridge Docker. É uma
  nota de troubleshooting do ambiente, não um requisito universal de instalação.
