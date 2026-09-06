# Current State

## Fase atual: 2A — AUTH + SECURITY MODEL

- Branch de trabalho: `phase/auth-security-model`.
- [AUTH.md](AUTH.md) especifica conta, credenciais, link token de alta entropia,
  código humano protegido por HMAC, sessões, access/refresh opacos, recuperação,
  reautenticação, Security Gate, limites e auditoria.
- [THREAT_MODEL.md](THREAT_MODEL.md) registra ameaças, mitigações propostas e riscos
  residuais; não declara controles de autenticação já implementados.
- [ADR-006](ADR/ADR-006-authentication-session-strategy.md) e
  [ADR-007](ADR/ADR-007-reauthentication-security-gate.md) registram decisões de desenho.
- Implementação de auth ainda não iniciada: nenhum endpoint, modelo SQL, migration
  ou dependência nova. As decisões da Foundation permanecem preservadas.
- Os resultados de Foundation abaixo são o registro histórico da etapa anterior;
  não constituem testes das políticas de autenticação propostas nesta fase.

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

## Not validated:

- Gitleaks local permanece pendente; o scanner continua configurado no CI.
- Políticas da Fase 2A, incluindo concorrência de refresh, revogação e recuperação:
  são especificações e ainda não têm implementação para teste.

## Known blockers:

- Nenhum bloqueador técnico conhecido para a foundation; Gitleaks local ainda não foi
  instalado neste ambiente.
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

- `a78793cd9e02e631cb50b6931bc00a90023ea24d` — `chore: establish Bots Central V2 foundation`.
- Documentação da Fase 2A em alterações locais, sem commit ou push nesta etapa.
