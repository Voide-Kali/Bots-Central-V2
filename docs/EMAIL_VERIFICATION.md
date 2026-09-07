# Email Verification Security Contract

Status: a Fase 2B.4B implementa a fundação de persistência e material: tabela/model,
migration `0003`, enums, token/código, framing HMAC e keyring. A Fase 2B.4C implementa
o staging de issuance/resend síncrono no domínio, sem delivery. Consume, ativação,
entrega e endpoint não existem.
O escopo continua somente `email_verification` para `User` em `pending_verification` e
seu `UserEmail` específico não verificado.

## Estratégia e materiais

Adotar a tabela específica `email_verification_challenges` (ADR-008), não uma tabela
genérica. Isso preserva constraints claras e não acopla esta fase a recovery, sessões
ou Security Gate.

- **Link:** 32 bytes de CSPRNG, externamente base64url canônico sem padding: exatamente
  43 caracteres ASCII. Validação futura rejeita padding, caracteres fora de base64url,
  tamanho diferente de 43 e decodificação diferente de 32 bytes; persistir somente
  `SHA-256(token_bytes)` (32 bytes), nunca hash da string textual. TTL máximo de 15
  minutos, uso único.
- **Código:** exatamente oito dígitos ASCII; a apresentação pode ser `1234 5678`.
  Persistir somente HMAC-SHA-256 (32 bytes); TTL de 10 minutos, no máximo 5 tentativas
  válidas e uso único. SHA-256 simples é proibido para esse material de ~27 bits.

Plaintext existe apenas entre geração e entrega futura, jamais em banco, logs, audit,
telemetria ou filas. A fundação gera material somente em memória e não o persiste
automaticamente. Abrir link por GET nunca o consome; uma operação explícita futura o
fará. Não há provedor SMTP/Gmail nesta fase.

Verificação humana recebe conceitualmente `challenge_id` + `code`. `challenge_id` é
UUID opaco público, não secreto e não autenticador: ele somente localiza o challenge.
Não há lookup global por código; todos os vínculos, estados e o HMAC ainda são validados.

## HMAC e chaves

Para código, usar HMAC-SHA-256 padrão sobre campos length-prefixed em ordem fixa:

```text
u32be(len(protocol)) || protocol UTF-8 ||
u32be(16) || challenge_id UUID bytes ||
u32be(len(purpose)) || purpose ASCII ||
u32be(16) || user_id UUID bytes ||
u32be(16) || user_email_id UUID bytes ||
u32be(8) || normalized_code ASCII
```

`len` é o comprimento em **bytes** do campo codificado e `u32be` é um unsigned
32-bit big-endian. `protocol` é UTF-8 ASCII
`bots-central.email-verification-code-hmac.v1`; `purpose` é ASCII
`email_verification`; UUIDs usam exatamente 16 bytes em network byte order
(`UUID.bytes`); e código usa exatamente 8 bytes ASCII. `user_id` é derivado do
`UserEmail` autoritativo, não gravado no challenge. Não concatenar texto sem framing,
nem usar JSON. A comparação futura usa a primitiva constant-time da biblioteca.

O pepper tem no mínimo 256 bits, gerados por CSPRNG, e é fornecido em runtime como
valor base64url canônico por configuração externa: uma versão ativa e um mapa JSON de
`version → secret` compatível com `pydantic-settings`. Os valores usam máscara de
segredo. A configuração é opcional no startup global para não quebrar componentes que
não usam email verification, mas a construção do keyring falha fechada se estiver
ausente, inválida, curta, não canônica ou sem a versão ativa. Não há default/fallback,
inclusive em development/test; testes fornecem chave efêmera explicitamente. Segredos
não ficam em PostgreSQL, Git, imagem ou logs. Um secret manager ou KMS pode substituir
a injeção de configuração no futuro, sem mudar o contrato.

O challenge de código armazena apenas `hmac_key_version`. Nova emissão usa a chave
ativa; validação escolhe exatamente a versão gravada. Durante rotação, manter chave
anterior para validação por pelo menos 20 minutos após a última emissão: TTL de código
de 10 minutos mais 10 minutos de margem de relógio/operação. Versão desconhecida é
rejeitada, sem tentar outra chave. Rotação emergencial remove/desabilita a versão,
invalida challenges ativos daquela versão com `key_compromised` e nunca tenta outra
chave; links não dependem do pepper.

## Schema conceitual para migration 0003

`0003` cria os enums `email_verification_material_type` (`link`, `code`) e
`email_verification_invalidation_reason` (`superseded`, `attempts_exhausted`,
`account_state_changed`, `email_already_verified`, `key_compromised`), e a tabela
`email_verification_challenges` com: `id UUID` (PK), `user_email_id UUID NOT NULL`
(FK `user_emails.id RESTRICT`), `material_type`, `link_token_digest BYTEA NULL`,
`code_digest BYTEA NULL`, `hmac_key_version VARCHAR(64) NULL`, `attempt_count INTEGER
NULL`, `max_attempts INTEGER NULL`, `created_at`, `expires_at`, `consumed_at NULL`,
`invalidated_at NULL` e `invalidation_reason NULL`. Purpose é implícito pela tabela;
`UserEmail` determina autoritativamente o `User`.

Checks exatos: `expires_at > created_at`; `consumed_at` e `invalidated_at` mutuamente
exclusivos; e `invalidation_reason IS NULL` exatamente quando `invalidated_at IS NULL`.
Para `link`: digest link não nulo com `octet_length=32`, digest de código e versão HMAC
nulos, e `attempt_count`/`max_attempts` nulos. Para `code`: digest link nulo, digest de
código não nulo com `octet_length=32`, versão HMAC não nula/não vazia,
`max_attempts=5` e `0 <= attempt_count <= 5`. Expiração é derivada de `expires_at`,
nunca motivo de invalidação.

`superseded` é usado por resend; `attempts_exhausted` ao quinto código incorreto;
`account_state_changed` para conta que deixou de ser pendente, incluindo locked/disabled;
`email_already_verified` quando o alvo já foi confirmado; e `key_compromised` na
rotação emergencial. Esses são os únicos motivos iniciais.

Índices: único parcial para `link_token_digest` não nulo, índice por `user_email_id`,
e `(user_email_id, created_at DESC)` para emissão/resend/cleanup. Não indexar digest de
código: a entrada de código sempre inclui `challenge_id` e o HMAC é recomputado após
carregar a linha.

## Serviços operacionais: issuance/resend e consumo futuro

**Issuance/resend** carrega e trava o `UserEmail` alvo com `SELECT … FOR UPDATE`. Ele é
a âncora estável que serializa inclusive a primeira emissão, quando não há challenge
para travar. Deriva então `user_id`, trava `User`, confirma que conta e e-mail ainda
podem participar e que o e-mail não está verificado; só depois consulta challenges,
aplica cooldown, trava siblings vivos, invalida os anteriores e cria o novo challenge.
**Ordem global obrigatória neste domínio:** `UserEmail` → `User` →
`EmailVerificationChallenge`. Nunca adquirir esses locks em ordem inversa.

O serviço de domínio recebe uma `Session` síncrona com transação pertencente ao caller:
usa savepoint e `flush`, mas não faz commit nem rollback da transação externa. Após os
locks de `UserEmail` e `User`, obtém uma única vez `SELECT clock_timestamp()`; este é o
tempo autoritativo para decisão, `created_at`, cooldown, `invalidated_at` e TTL. LINK e
CODE compartilham cooldown de 60 segundos por `user_email_id`. Somente siblings vivos
(`consumed_at`/`invalidated_at` nulos e `expires_at` futuro) recebem `superseded`; um
challenge expirado continua apenas expirado.

O resultado é `StagedLinkChallenge` ou `StagedCodeChallenge`: contém plaintext somente
como `SecretStr`, não implica commit e só pode ser entregue depois de commit externo bem
sucedido. A ordem futura obrigatória é `stage → caller commit → delivery`; não existe
delivery, SMTP, fila ou outbox nesta fase.

**Consume de código:** lookup inicial por `challenge_id` sem lock somente descobre
`user_email_id`; inexistente retorna resultado interno inválido/genérico. Em seguida
trava `UserEmail`, deriva/trava `User` e por último trava/recarrega o challenge. Só então
revalida integralmente id, vínculo, material, prazo, estado terminal, pertencimento de
e-mail e estado de conta antes de verificar HMAC/código. O lookup inicial não é
autoridade.

**Consume de link:** validar formato canônico, decodificar 32 bytes e calcular
`SHA-256(token_bytes)`; o lookup inicial por digest é também apenas candidato. Depois
trava `UserEmail`, `User` e challenge nessa ordem, e revalida digest, vínculo, material,
prazo e estados antes de consumir. Consume e resend do mesmo `UserEmail` são assim
serializados: resend não invalida no meio de consumo, nem há inversão UserEmail/challenge.

Para código, aceitar somente `12345678` ou `1234 5678`: remover no máximo o único
espaço central de apresentação, depois exigir oito bytes ASCII `0`–`9`. Hífen, dígitos
Unicode e qualquer outro formato são rejeitados sem tentativa. Código normalizado válido
mas incorreto incrementa `attempt_count`; ao chegar a 5, marcar `invalidated_at` com
`attempts_exhausted` na mesma transação. Expirado, consumido ou já invalidado não muda
contador. Link inválido não tem contador de adivinhação.

Resend usa a chave lógica `user_email_id` (purpose é implícito), cooldown mínimo de 60
segundos desde a última emissão e o lock do `UserEmail`. Nunca reutiliza plaintext, não
prolonga TTL anterior e não zera futuros orçamentos globais de abuso.

## Transição, transporte e retenção

No mesmo commit do consumo válido: confirmar `User` pendente, o `UserEmail` vinculado
e ainda não verificado; marcar `verified_at`, transicionar `pending_verification` para
`active`, marcar o challenge usado como consumido e invalidar quaisquer siblings não
terminais do mesmo `UserEmail` com `email_already_verified`. Conta `locked` ou `disabled`
nunca é reativada; challenge é invalidado. E-mail já verificado também invalida challenge
ativo sem alterar estado. Retry de challenge já consumido é resultado interno
seguro/idempotente, sem nova transição. Nenhuma sessão, token ou autenticação é criada.

O domínio pode distinguir inexistente, expirado ou duplicado. Transporte HTTP futuro
deve responder genericamente onde existência revelaria conta/challenge. Logs normais
registram somente outcome sanitizado, purpose, timestamp e correlation ID futuro; audit
pode incluir `challenge_id` e `user_email_id`, derivando `user_id` quando necessário.
Nunca registrar plaintext, digest completo, HMAC key ou configuração secreta.

**Baseline inicial de design:** manter challenge expirado/consumido/inválido por 30 dias
após seu estado terminal ou expiração para investigação operacional limitada; então
removê-lo por job futuro. A política final exige revisão de privacidade/LGPD, necessidade
operacional, retenção de audit e minimização de dados. Registro de challenge não substitui
audit de longo prazo e não retém materiais secretos.

## Test plan obrigatório para 2B.4B/2B.4C

PostgreSQL real: enums/checks, tamanhos de digest, unicidade de token, token canônico
de 43 caracteres, padding/não-canônico rejeitado, formato de código, `challenge_id` +
código sem lookup global, erro/tentativa/exaustão, expiração, invalidação e resend.
Também: primeira emissão concorrente, resend concorrente, serialização pelo lock de
`UserEmail`, corrida de consumo, consume-vs-resend e resend-vs-consume em sessões
PostgreSQL independentes sem deadlock, uma só transação semanticamente vencedora,
lookup inicial alterado antes dos locks detectado na revalidação, siblings invalidados
em sucesso, corrida locked/disabled sem ativação, binding derivado via `UserEmail` sem
`user_id` redundante, versão desconhecida, invalidação por chave comprometida, rotação,
digest malformado, rollback e ausência de vazamento de segredo em repr/log/audit.
