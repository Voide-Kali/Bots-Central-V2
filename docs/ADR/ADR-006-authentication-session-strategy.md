# ADR-006: Authentication and Session Strategy

Status da decisão: aceita.

Status de implementação: MVP-1 implementa login de contas ativas, sessões PostgreSQL, access/refresh tokens opacos, rotação, revogação por replay, logout e `auth/me`. Recovery, métodos fortes e políticas futuras permanecem pendentes.

## Contexto

A plataforma precisa identificar contas e revogar sessões antes de permitir ações
em dispositivos. Clientes futuros terão contextos diferentes, mas não podem acessar
o banco ou confiar exclusivamente em dados emitidos no passado. A Foundation já
define FastAPI no monólito modular e PostgreSQL como fonte de verdade.

Senha, e-mail e recuperação também são superfícies de ataque. Sessões precisam de
ciclo de vida explícito e tratamento de replay sem criar serviço de identidade,
Redis ou protocolos criptográficos próprios. Esta fase decide contratos conceituais,
não endpoints, tabelas, migrations ou bibliotecas instaladas.

## Decisão

- Modelar conceitualmente User, e-mail verificado, credencial de senha, estados
  `pending_verification`, `active`, `locked`, `disabled` e estado de segurança separado.
- Adotar Argon2id com salt por gravação, parâmetros configuráveis/validados e rehash
  futuro por biblioteca. Limites e política de senha estão em [AUTH.md](../AUTH.md).
- Manter sessões server-side no PostgreSQL; validar conta, sessão e versão de
  segurança a cada chamada protegida. Revogação não aguarda o access token expirar.
- Access token bearer opaco de 256 bits CSPRNG com duração inicial de 10 minutos,
  armazenado somente como digest SHA-256 e vinculado server-side a sessão/usuário.
  Cada uso resolve e revalida sessão, conta e `security_version` no PostgreSQL.
  Não incluir plaintext no banco, logs ou URL.
- Refresh opaco de 256 bits, somente digest SHA-256 no servidor, uma família por
  sessão, rotação a cada uso e transação serializada no PostgreSQL. Sessão: até 30
  dias absolutos e 7 dias ociosos; refresh não ultrapassa esses prazos.
- Token consumido reapresentado revoga sua família/sessão. Preservar digests
  consumidos até expirar a família. Sem grace period: resposta perdida/refresh
  concorrente pode exigir novo login. Digest desconhecido não revoga vítima arbitrária.
- Desafios de e-mail são aleatórios, limitados, curtos, single-use e vinculados a
  purpose/usuário/contexto. Interface de entrega interna é conceitual e sem provedor.
- Recuperação usa e-mail previamente verificado ou recovery codes independentes,
  exibidos uma vez e armazenados só como digest. Não emite sessão normal; reset
  revoga sessões, invalida credenciais auxiliares antigas e exige login posterior.
- Mudanças críticas de credenciais seguem revogação explícita e restrições de
  recuperação. Trusted sessions/devices e MFA forte precisam de decisão futura.
- Contadores, desafios e auditoria inicialmente compartilham PostgreSQL no monólito;
  detalhes operacionais e critérios de aceitação estão em [AUTH.md](../AUTH.md).

## Consequências

Revogação explícita e política central prevalecem sobre disponibilidade offline:
requisições protegidas dependem do banco e devem falhar com segurança se ele falhar.
O token opaco evita gerenciamento de chaves e parsing criptográfico enquanto toda
requisição protegida já depende do PostgreSQL. JWT pode ser reconsiderado somente
com necessidade concreta de validação distribuída/offline entre serviços e novo ADR.

A política de refresh estrita reduz ambiguidade de replay, mas torna retries após
perda de resposta e concorrência mais custosos. Clientes deverão serializar refresh.
Os prazos/limites são propostas do projeto a validar antes de ativação.

Um bearer access token opaco roubado pode ser utilizado até revogação/expiração, e refresh roubado
pode ser usado primeiro. E-mail pode ser comprometido e não é MFA forte. Novos
poderes remotos exigem política de evidência reforçada, não apenas senha/e-mail.

Alternativas consideradas: JWT stateless e JWT com consulta server-side foram adiados;
ambos adicionam chaves, parsing e superfície de ataque sem benefício inicial no
monólito. Serviço de auth separado e Redis não se justificam nesta fase.

Bibliotecas, operação/rotação do pepper HMAC, retenção, entrega e transferência de identidade
sem e-mail precisam de revisão antes de implementação. Riscos estão em
[THREAT_MODEL.md](../THREAT_MODEL.md). ADRs 001–005 permanecem válidos.
