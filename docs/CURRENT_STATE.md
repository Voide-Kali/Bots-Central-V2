# Current State

## MVP-1 backend auth/devices

Final host gate passed — ready for checkpoint. Integration into `mvp1/integration`
remains pending. The `mvp1/backend-auth-devices` track implements ACTIVE-account
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
Authenticated owner device listing exposes the persisted fingerprint for the future
Web human-comparison flow; frontend integration remains pending.
This is Backend-only: Agent implementation, cross-repository integration, remote actions,
and invasive collection remain out of scope and unimplemented.

Host validation confirmed: full backend suite `326 passed`, `0 failed`, coverage
`89%`; targeted MVP-1 authentication/HTTP/migration suite `38/38 passed`. Migration
`0004 ↔ 0005` round-trip passed against the dedicated `bots_central_test`
PostgreSQL database; Alembic head is `0005_device_foundation`. Validation includes
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
  A listagem retorna `offline` conservadoramente; presence real ainda não existe.

## Design approved

- Contrato operacional de email verification da Fase 2B.4A, incluindo key rotation,
  concorrência, retenção, locks, issuance/resend e consume; operação da rotação de
  chaves HMAC e retenção de email verification permanecem futuras.

## Pending integration / Not implemented

- Integração do Backend MVP-1 na branch `mvp1/integration` permanece pendente.
- Device Online: pairing/enrollment, credenciais/autenticação de Agent, heartbeat
  e presence real ainda não estão implementados no Backend.
- Remote actions, Security Gate completo e Task Engine futuro permanecem fora
  deste MVP-1.
- Recovery, auditoria durável, verificação de e-mail secundário em ACTIVE e
  suporte CORS cross-origin aprovado permanecem pendentes.
- Integração operacional com Agent/mobile e contrato de refresh para clientes
  nativos permanecem futuros.

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
- Recovery, Security Gate completo, Task Engine, Device Online e ações remotas
  ainda não têm implementação operacional para validar. Emissão/rotação de tokens,
  revogação por replay e logout/revogação já foram validados no MVP-1.

## Pendências conhecidas:

- Gitleaks local continua pendente de instalação/execução.
- Operação das chaves HMAC, retenção e critérios de recuperação sem e-mail
  permanecem pendentes para os respectivos fluxos futuros; login, sessões,
  tokens e revogação do MVP-1 já estão implementados e validados.
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
