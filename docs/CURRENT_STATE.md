# Current State

## Fase atual: 2B.1 — AUTH DOMAIN + DATABASE FOUNDATION

- Branch de trabalho: `phase/auth-database-foundation`.
- [AUTH.md](AUTH.md), [THREAT_MODEL.md](THREAT_MODEL.md), [ADR-006](ADR/ADR-006-authentication-session-strategy.md)
  e [ADR-007](ADR/ADR-007-reauthentication-security-gate.md) permanecem o desenho aprovado.
- A migration `0002_auth_database_foundation` adiciona somente `users`, `user_emails`,
  `password_credentials`, `sessions`, `access_tokens` e `refresh_tokens`; consulte
  [DATABASE.md](DATABASE.md) para relações, índices, invariantes e dados sensíveis.
- Foram adicionados modelos SQLAlchemy, enums controlados e repositório de lookup por ID,
  e-mail canônico e digest. Não há emissão/verificação de credencial nem endpoint de auth.
- A validação PostgreSQL real da Fase 2B.1 foi executada no banco dedicado
  `bots_central_test`; não foram criados endpoints ou fluxos de autenticação.

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

## Not validated:

- Gitleaks local permanece pendente; o scanner continua configurado no CI.
- Políticas da Fase 2A, incluindo emissão/rotação de refresh, revogação operacional,
  recuperação e Security Gate, continuam sem implementação para teste.

## Known blockers:

- Gitleaks local continua pendente de instalação/execução.
- Antes de implementar/ativar auth: decidir bibliotecas e operação das chaves,
  validar parâmetros/limites, retenção e critérios de recuperação sem e-mail.
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

## Ainda não implementado

- Autenticação, usuários, identidade de dispositivo, QR Code, integrações, agentes,
  automações, mobile, IA, dashboard, WebSocket e tabelas de domínio.

## Commit atual

- `bd640c3` — `docs: define authentication and security model`.
- A Fase 2B.1 está em alterações locais, sem commit ou push nesta etapa.
