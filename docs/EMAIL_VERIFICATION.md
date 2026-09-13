# Email Verification Security Contract

Status: a Fase 2B.4B implementa a fundação de persistência e material: tabela/model,
migration `0003`, enums, token/código, framing HMAC e keyring. A Fase 2B.4C implementa
o staging de issuance/resend síncrono no domínio, sem delivery. A Fase 2B.4D implementa
consume síncrono de CODE/LINK e ativação atômica da conta pendente. A Fase 2B.4E adiciona
somente uma fundação interna de application/delivery, sem endpoint HTTP, provider,
background task, fila, outbox, login, sessão ou token de autenticação. A Fase 3A expõe
somente a boundary HTTP anônima de verificação, limiter PostgreSQL e adapter SMTP
STARTTLS; login, sessão, token, outbox e retry durável continuam fora do escopo.
O escopo continua somente `email_verification` para `User` em `pending_verification` e
seu `UserEmail` específico não verificado.

## Estratégia e materiais

Adotar a tabela específica `email_verification_challenges` (ADR-008), não uma tabela
genérica. Isso preserva constraints claras e não acopla esta fase a recovery, sessões
ou Security Gate.

- **Link:** 32 bytes de CSPRNG, externamente base64url canônico sem padding: exatamente
  43 caracteres ASCII. A validação rejeita padding, caracteres fora de base64url,
  tamanho diferente de 43 e decodificação diferente de 32 bytes; persistir somente
  `SHA-256(token_bytes)` (32 bytes), nunca hash da string textual. TTL máximo de 15
  minutos, uso único.
- **Código:** exatamente oito dígitos ASCII; a apresentação pode ser `1234 5678`.
  Persistir somente HMAC-SHA-256 (32 bytes); TTL de 10 minutos, no máximo 5 tentativas
  válidas e uso único. SHA-256 simples é proibido para esse material de ~27 bits.

Plaintext existe apenas entre geração e entrega futura, jamais em banco, logs, audit,
telemetria ou filas. A fundação gera material somente em memória e não o persiste
automaticamente. O consume recebe material somente em memória. Abrir link por GET
nunca o consome; o serviço de domínio exige chamada explícita e ainda não tem transporte
HTTP. Não há provedor SMTP/Gmail nesta fase.

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
nem usar JSON. A comparação usa a primitiva constant-time da biblioteca.

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
rejeitada com `KeyVersionUnavailable`, sem mutação, incremento ou tentativa de outra
chave; não marca automaticamente `key_compromised`. A operação de rotação emergencial
permanece futura: remove/desabilita a versão,
invalida challenges ativos daquela versão com `key_compromised` e nunca tenta outra
chave; links não dependem do pepper.

## Schema implementado pela migration 0003

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

## Serviços operacionais: issuance/resend e consume

**Issuance/resend** carrega e trava o `UserEmail` alvo com `SELECT … FOR UPDATE`. Ele é
a âncora estável que serializa inclusive a primeira emissão, quando não há challenge
para travar. Deriva então `user_id`, trava `User`, confirma que conta e e-mail ainda
podem participar e que o e-mail não está verificado; só depois consulta challenges,
aplica cooldown, trava siblings vivos, invalida os anteriores e cria o novo challenge.
**Ordem global obrigatória neste domínio:** `UserEmail` → `User` →
`EmailVerificationChallenge`. Nunca adquirir esses locks em ordem inversa.

O serviço de issuance recebe uma `Session` síncrona com transação pertencente ao caller:
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

### Fundação application/delivery 2B.4E

`email_verification_application` é a autoridade da transação externa: recebe uma
session factory, cria e fecha sua própria `Session`, e deixa o bloco `session.begin()`
normalmente antes de devolver qualquer resultado. Registro e issuance compartilham a
mesma transação: `register_user()` faz flush, a camada application localiza exatamente
um `UserEmail` primário pelo `user_id`, chama issuance e só então ocorre o único commit.
Duplicidade de registro retorna resultado application sanitizado sem resend implícito,
challenge ou intent de delivery. Zero ou mais de um e-mail primário é invariant error.

Resend localiza o e-mail canonical internamente, executa issuance na transação própria e
retorna resultado sanitizado com zero intent para desconhecido, verificado, cooldown ou
conta inelegível. CODE e LINK consume também são chamados dentro da transação própria;
`WrongCode`, `AttemptsExhausted`, `AlreadyVerified` e `AccountNotEligible` saem do bloco
normalmente para que suas mutações sejam commitadas antes de qualquer mapeamento futuro
de transporte. Exceptions de banco/invariante/programação fazem rollback normal.

Após commit bem-sucedido, issuance pode produzir `DeliveryIntent`: DTO Python puro,
ORM-free e Session-free com destinatário, challenge ID, prazo, material type e plaintext
em `SecretStr` redigido. O intent nunca é resultado público de transporte e não contém
User, UserEmail, Challenge, Session ou relação lazy. Falha de commit não devolve intent.

`dispatch_delivery()` faz uma única tentativa best-effort por invocation. O adapter futuro
deve manter retries automáticos desabilitados. Falha retorna `DeliveryFailed` sanitizado,
sem exception/provider body/destinatário/plaintext e sem retry. Não há alegação de
exactly-once, at-least-once ou at-most-once fim-a-fim.

Não há persistence de delivery, outbox ou migration. O tradeoff deliberado é:
`COMMIT → processo morre/falha antes de delivery → challenge persiste → plaintext se perde
→ usuário aguarda cooldown → resend cria material novo`. Provider acceptance pode ser
ambígua; não se reutiliza automaticamente o mesmo segredo. Isso é disponibilidade, não
alteração da integridade do challenge.

### Boundary HTTP e delivery 3A

As únicas rotas anônimas são `POST /api/v1/auth/register`,
`POST /api/v1/auth/email-verification/resend`,
`POST /api/v1/auth/email-verification/consume-code` e
`POST /api/v1/auth/email-verification/consume-link`. A route faz apenas validação de
envelope, admission de abuso, chamada à application layer, mapeamento público e eventual
agendamento pós-resposta. Ela nunca abre a transação externa do domínio: application já
commita antes de qualquer resposta ou I/O. `WrongCode`, `AttemptsExhausted`,
`AlreadyVerified` e `AccountNotEligible` permanecem outcomes normais commitados antes do
mapeamento HTTP.

Registro novo e duplicado recebem exatamente `202` com corpo genérico. Resend staged,
unknown, verified, cooldown e ineligible recebem a mesma resposta. Consume CODE/LINK
retorna somente `200 {"verified": true}` para `ConsumedEmailVerification`,
`AlreadyConsumed` e `AlreadyVerified`; estes dois últimos são sucesso idempotente seguro.
Todo outro outcome normal retorna o único `400 {"verified": false}`, sem contador,
status de conta, motivo de invalidação, versão HMAC ou existência de challenge.
`KeyVersionUnavailable` é outcome normal e pertence a esse mesmo grupo de falha, sem
virar oráculo de versão ou existência. Erros globais de configuração/keyring, invariante
ou banco permanecem falha sanitizada de servidor. Erros de envelope usam resposta
genérica sem ecoar input; respostas auth usam `Cache-Control: no-store`.
`Retry-After` não revela cooldown ou estado de challenge.

Todo POST auth aceita somente JSON e é limitado antes de validação de domínio: registro
8 KiB, demais endpoints 1 KiB; e-mail até 320 caracteres, senha até 1024, CODE até 9
e LINK até 43. A validação de domínio ainda é a autoridade. Não há CORS nesta topologia
same-origin; form posts são rejeitados e Origin, quando presente, deve ser o
`PUBLIC_ORIGIN` configurado. Clientes nativos podem omitir Origin.

`auth_abuse_buckets` é limiter PostgreSQL de janela fixa, compartilhado e atômico. Ele
persiste somente HMAC-SHA-256 pseudonimizado com segredo próprio (`ABUSE_CONTROL_HMAC_KEY`),
separado do keyring CODE: nunca e-mail plaintext, senha ou secret de challenge. Orçamentos
atuais são: registration 5/identificador/h, 30/rede/h e 300 global/min; resend 5/
identificador/h, 20/rede/h e 300 global/h; CODE 10/challenge/15 min, 30/rede/15 min e
1000 global/15 min; LINK 60/rede/15 min e 1500 global/15 min. Falha da autoridade do
limiter nega temporariamente a operação. Cooldown de 60 segundos é defesa de domínio,
não substituto do limiter. Endereços de cliente usam peer/socket por padrão; somente um
`X-Forwarded-For` de valor único é aceito quando o peer coincide exatamente com
`TRUSTED_PROXY_IP`. Se o peer for o proxy confiável, XFF ausente, vazio, inválido,
duplicado ou com múltiplos endereços falha fechado; nunca se usa o endereço do proxy
como fallback. Multi-hop, cadeias CIDR, trusted-hop walking e parser RFC Forwarded
complexo estão fora da Phase 3A. O proxy deve remover/sobrescrever qualquer XFF externo
e enviar exatamente um endereço de cliente. IPv4 é agregado em /24 e IPv6 em /64.

Registro passa por admission antes de Argon2 e executa o trabalho síncrono fora do event
loop, com limite local configurável `ARGON2_MAX_CONCURRENCY` (default 2). Esse limite
protege um processo; o PostgreSQL é a autoridade multi-worker/multi-instância. Não há
Redis.

Após retorno pós-commit de `DeliveryIntent`, FastAPI/Starlette envia o corpo HTTP e só
então executa `dispatch_delivery()` em `BackgroundTasks`. O dispatcher chama o adapter no
máximo uma vez e não afeta resposta, status do provider ou transação. É in-process e não
durável: crash após commit perde plaintext, challenge persiste e resend posterior produz
material novo. SMTP é configurável por `EMAIL_VERIFICATION_DELIVERY_MODE=smtp`, `SMTP_HOST`,
`SMTP_PORT`, `SMTP_SENDER`, credenciais opcionais e timeout; ele usa STARTTLS com validação
padrão de certificado e não possui retry automático. Em produção, delivery `smtp`, SMTP
válido e `PUBLIC_ORIGIN` HTTPS válida são obrigatórios no startup; `disabled` só é aceito
em development/test. Não registrar payload, destinatário completo, credenciais, CODE ou LINK.
`SMTP_CA_FILE` é opcional e permite adicionar um bundle PEM de uma CA interna ao contexto
verificado normal do sistema. O arquivo é validado no startup; suas raízes são adicionadas,
nunca substituem as raízes do sistema, e não há modo que desative validação de certificado ou
hostname.
O adapter SMTP é síncrono e executa no threadpool do Starlette; isso é dívida operacional
V1 aceita: há timeout e admission de delivery, e um limiter dedicado poderá ser avaliado
após métricas. Não adicionar Redis, outbox ou fila nesta fase.

`PUBLIC_ORIGIN` é a única fonte de links LINK. É origem absoluta normalizada, sem path,
query, fragment ou userinfo; produção exige HTTPS e rejeita localhost/loopback. Em
development/test, HTTP é permitido somente para localhost/loopback. Nunca derivar a origem
de Host, X-Forwarded-Host, Origin ou input do cliente.

`GET /email-verification` nunca consome. A página não usa recursos de terceiros e recebe
o token em `#token=...`; captura somente o formato canônico em memória, remove o fragmento
com `history.replaceState()` e exige clique explícito antes do POST JSON. Não usa query,
path, cookie, localStorage ou sessionStorage. Ela responde com `no-store`,
`Referrer-Policy: no-referrer`, `nosniff`, CSP com nonce, `base-uri 'none'`,
`object-src 'none'`, `frame-ancestors 'none'` e `X-Frame-Options: DENY`.

Respostas iguais não tornam os fluxos constant-time. Diferenças de banco, locks, locator
e HMAC continuam riscos residuais; provider está fora do caminho crítico, mas não há
sleep artificial nem alegação de tempo constante. Revisão/medição de timing e auditoria
durável permanecem requisitos operacionais futuros.

**Consume de código** (`consume_email_verification_code`): checks de tipo exigem UUID,
string e keyring; o guard rejeita `Session.new`/`dirty`/`deleted` antes de qualquer query
ou savepoint. Dentro de `begin_nested()`, o lookup inicial projection-only por
`challenge_id`, sem lock, lê apenas candidate id e `user_email_id`; inexistente retorna
`InvalidChallenge`. Em seguida
trava `UserEmail`, deriva/trava `User` e por último trava/recarrega o challenge. Só então
revalida integralmente id, vínculo, material, prazo, estado terminal, pertencimento de
e-mail e estado de conta antes de verificar HMAC/código. O lookup inicial não é
autoridade.

**Consume de link** (`consume_email_verification_link`): validar formato canônico,
decodificar 32 bytes e calcular
`SHA-256(token_bytes)`; o lookup inicial por digest é também apenas candidato. Depois
trava `UserEmail`, `User` e challenge nessa ordem, e revalida digest, vínculo, material,
prazo e estados antes de consumir. Consume e resend do mesmo `UserEmail` são assim
serializados: resend não invalida no meio de consumo, nem há inversão UserEmail/challenge.
O locator de LINK também projeta somente candidate id e `user_email_id`; token malformado
ou ausente retorna `InvalidChallenge`. LINK não recebe nem resolve keyring.

Todos os loads autoritativos travados de `UserEmail`, `User`, target e siblings usam
`populate_existing=True`, inclusive quando a sessão já contém objetos no identity map.
Depois dos locks de `UserEmail → User → Challenge`, consume lê exatamente uma vez
`SELECT clock_timestamp()`. Esse `decision_time` controla expiração, `consumed_at`,
`invalidated_at`, `verified_at` e os `updated_at` de User/UserEmail no sucesso; estes
últimos são atribuídos explicitamente para não usar o `onupdate=now()` dos modelos.
Não usa relógio Python nem o início da transação PostgreSQL para decisões operacionais.

A precedência pós-lock é: binding/id/material/digest incompatível → `InvalidChallenge`;
consumido → `AlreadyConsumed`; invalidado → `Invalidated(reason)`;
`decision_time >= expires_at` → `Expired`; e-mail verificado → `AlreadyVerified`,
invalidando o target vivo com `email_already_verified`; conta não pendente →
`AccountNotEligible(status)`, invalidando o target vivo com `account_state_changed`.
Consumido, invalidado e expirado não sofrem mutação. E-mail verificado
não modifica User. `ACTIVE` também não é elegível nesta fase: verificação de e-mail
secundário em conta active é fase futura. `LOCKED`/`DISABLED` nunca são reativados.

Para código, aceitar somente `12345678` ou `1234 5678`: remover no máximo o único
espaço central de apresentação, depois exigir oito bytes ASCII `0`–`9`. Hífen, dígitos
Unicode e qualquer outro formato são rejeitados sem tentativa. Código normalizado válido
mas incorreto incrementa `attempt_count`; ao chegar a 5, marcar `invalidated_at` com
`attempts_exhausted` na mesma transação. Expirado, consumido ou já invalidado não muda
contador. Link inválido não tem contador de adivinhação.

Formato rejeitado retorna `MalformedCode`. Depois da normalização e antes de resolver
chave/verificar HMAC, um CODE já com `attempt_count >= max_attempts` mas ainda não
terminal é invalidado como `attempts_exhausted`, com `flush`, e retorna
`AttemptsExhausted`. A versão HMAC é exatamente a persistida; versão ausente retorna
`KeyVersionUnavailable` sem alteração. Mismatch válido incrementa uma vez e retorna
`WrongCode(attempt_count, attempts_remaining)` ou, no quinto erro, `AttemptsExhausted`.
Ambos são resultados normais commitáveis, nunca exceptions para forçar rollback.

Resend usa a chave lógica `user_email_id` (purpose é implícito), cooldown mínimo de 60
segundos desde a última emissão e o lock do `UserEmail`. Nunca reutiliza plaintext, não
prolonga TTL anterior e não zera futuros orçamentos globais de abuso.

## Transição, transporte e retenção

No mesmo commit do consumo válido: confirmar `User` pendente, o `UserEmail` vinculado
e ainda não verificado; marcar `verified_at`, transicionar `pending_verification` para
`active`, marcar o challenge usado como consumido e invalidar os siblings vivos do mesmo
`UserEmail` com `email_already_verified`. O filtro exato é `user_email_id` igual,
`id != target.id`, `consumed_at IS NULL`, `invalidated_at IS NULL` e
`expires_at > decision_time`, com `FOR UPDATE` e `populate_existing=True`.
Siblings expirados/terminais e outros e-mails permanecem inalterados. Conta `locked` ou `disabled`
nunca é reativada; challenge é invalidado. E-mail já verificado também invalida challenge
ativo sem alterar estado. Retry de challenge já consumido é resultado interno
seguro/idempotente, sem nova transição. Nenhuma sessão, token ou autenticação é criada.

CODE e LINK compartilham a mesma transição privada e retornam
`ConsumedEmailVerification(challenge_id, user_email_id, consumed_at)` após `flush`.
Os outcomes são dataclasses frozen em union explícita e não carregam plaintext, digest
ou chave. Erros de tipo, invariantes ou banco são exceptions; falhas dentro do savepoint
não deixam transição parcial. O serviço não faz commit/rollback externo nem transação
autônoma. Rollback externo reverte inclusive tentativas, exaustão e invalidações.

**Regra obrigatória para integração futura:** `domain operation → caller COMMIT outer
transaction → somente DEPOIS mapear/serializar/enviar HTTP ou executar I/O externo`.
O caller deve commitar também `WrongCode` e `AttemptsExhausted`; não converter esses
outcomes em exceptions dentro do bloco transacional. Nenhuma resposta HTTP ou disconnect
do cliente pode decidir se `attempt_count` persiste. Commit falho não autoriza anunciar
sucesso nem executar I/O. Nesta fase não há endpoint nem implementação desse transporte.

Endpoints públicos continuam bloqueados até contrato de respostas genéricas, abuse
limiting e revisão de timing. Remover provider I/O do caminho HTTP futuro reduz um sinal
grande de timing, mas não afirma tempo constante: hash, lookup e banco continuam variando.
O futuro link usa `PUBLIC_ORIGIN` server-side confiável e HTTPS em produção, nunca Host
ou input do cliente. GET nunca consome; a boundary futura é página confiável, token em
fragmento preferencialmente, ação explícita do usuário e POST de consume protegido.

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

## Test plan para 2B.4B/2B.4C/2B.4D/2B.4E/3A

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

Os testes de consume usam PostgreSQL real e incluem CODE/LINK, precedência, tentativas,
commit/rollback externo, ativação, siblings, refresh do identity map e locator obsoleto.
As corridas consume-vs-consume e consume-vs-resend nos dois sentidos comprovam bloqueio
via `pg_backend_pid()`/`pg_blocking_pids()` em sessões separadas; espera temporal não é
prova de locking. Rotação emergencial, audit e transporte operacional continuam futuros.

Os testes application usam PostgreSQL real para confirmar composição atômica de registro
com issuance, rollback/commit externo, intenção de delivery somente após commit, DTO sem ORM
ou Session e repr sem plaintext. Também confirmam que outcomes mutáveis de consume persistem
antes de transporte futuro e que o dispatcher chama o adapter uma vez, sem retry, e sanitiza
falhas. A Fase 2B.4E não implementava provider, I/O externo, endpoint HTTP,
BackgroundTasks ou outbox.

Os testes 3A usam PostgreSQL real e ASGI para provar admission atômica concorrente,
expiração/cleanup do limiter, rejeição antes de Argon2, chave pseudonimizada, política de
proxy e migration. Eles também comparam respostas públicas de registration/resend/consume,
confirmam commits das mutações normais antes do mapeamento, body caps, ausência de eco de
input, página LINK inerte com headers, dispatch após o corpo ASGI e SMTP STARTTLS fake.
Não há teste de provider externo, retry durável, Redis, outbox ou garantia de entrega.
