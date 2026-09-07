# Database Foundation — Fase 2B.4B

## Escopo

Esta fase adicionou o armazenamento persistente consumido por fluxos de autenticação.
As Fases 2B.2 e 2B.3 usam este schema para hashing de senha e registro interno. A
Fase 2B.4B adiciona somente a fundação persistente de challenges de verificação de
e-mail. Não há endpoint, emissão de token, login, recuperação ou Security Gate.

PostgreSQL continua sendo a fonte autoritativa para estado de conta, sessão e
revogação. A migration `0002_auth_database_foundation` sucede
`0001_foundation` e pode ser revertida para esta última.

## Tabelas e relações

| Tabela | Responsabilidade |
| --- | --- |
| `users` | Conta com UUID, estado controlado, versão de segurança e timestamps UTC. |
| `user_emails` | Identidade de e-mail canônica, apresentação preservada, verificação e e-mail principal. |
| `password_credentials` | Um hash Argon2id por usuário, sem plaintext ou salt separado. |
| `sessions` | Sessão server-side, prazo absoluto/ocioso, estado de autenticação e revogação. |
| `access_tokens` | Digest SHA-256 de bearer access token futuro ligado a uma sessão. |
| `refresh_tokens` | Histórico de digests de refresh por família e geração para rotação e detecção de reuse futuros. |
| `email_verification_challenges` | Material de verificação de um `UserEmail` não verificado, persistido somente como digest e sem `user_id` redundante. |

As chaves estrangeiras usam `RESTRICT`: credenciais e histórico de token não são
apagados em cascata por acidente. Identificadores são UUIDs v4 gerados no servidor.

## Invariantes e índices

- `users.security_version` e `sessions.security_version` não podem ser negativos.
- `user_emails.email_canonical` é globalmente único e não vazio; há índice para
  `user_id` e índice parcial único que permite no máximo um e-mail principal por usuário.
- `password_credentials.user_id` é chave primária, portanto há no máximo uma
  credencial de senha atual por usuário.
- `email_verification_challenges.user_email_id` referencia `user_emails.id` com
  `RESTRICT`; `UserEmail` determina o `User` autoritativamente. A tabela específica
  tem somente materiais `link` e `code`: link exige digest SHA-256 de 32 bytes e não
  possui campos de tentativa/HMAC; code exige digest HMAC de 32 bytes, versão HMAC não
  vazia, `max_attempts=5` e contador entre 0 e 5. Expiração deve suceder a criação;
  consumo e invalidação são mutuamente exclusivos; timestamp e reason de invalidação
  são ambos nulos ou ambos preenchidos. Há unicidade parcial para digest de link,
  índice por `user_email_id` e índice `(user_email_id, created_at DESC)`; não há
  índice global para digest de código.
- Sessões exigem expiração absoluta e ociosa posteriores à criação; a ociosa não
  pode ultrapassar a absoluta. A janela de reautenticação é toda nula ou completa e
  ordenada.
- Digests de access e refresh token são únicos em suas respectivas tabelas, têm
  exatamente 32 bytes e expiram depois da criação. Há índice por `session_id`.
- `refresh_tokens.generation` é positiva; `(family_id, generation)` é único e há
  índices por família e por `(session_id, family_id)`.

O banco não força que todo usuário tenha e-mail principal nem que ele esteja
verificado. O serviço de registro atual cria o e-mail inicial como principal e não
verificado em sua unidade transacional; a constraint parcial evita dois principais
concorrentes. A rotação futura deverá confirmar, em transação, que sucessor, sessão e
família correspondem antes de gravar `replaced_by_id`.

## Normalização de e-mail

O schema separa `email_canonical` de `email_display`; o serviço interno de registro
fornece os valores conforme o contrato aprovado em [AUTH.md](AUTH.md): comparação sem
distinção de maiúsculas para local-part ASCII, domínio validado/normalizado por biblioteca
apropriada, preservação da apresentação e sem remoção de pontos ou sufixos `+`. Suporte
EAI e local-parts sensíveis a caixa continuam fora do escopo até revisão explícita. A
identidade canônica é única no banco para que a reserva seja atômica, inclusive em corridas.

## Dados sensíveis

`password_hash`, `token_digest`, digests de challenges e metadados de contexto são dados sensíveis. O schema
não possui campo de token plaintext, token bruto ou segredo. Plaintext de access/refresh
token só poderá existir durante emissão e verificação futuras, nunca em persistência,
URLs, `repr` ou logs. `repr` dos modelos omite hashes, digests e metadados.

O segredo HMAC de códigos de e-mail não está no PostgreSQL. O digest de link é
`SHA-256` dos 32 bytes do token, nunca da representação textual; o código humano usa
HMAC-SHA-256 e armazena a versão da chave, não a chave. A persistência existe, mas os
serviços de emissão, reenvio, consumo, ativação e cleanup ainda não foram implementados.

O hash de senha armazenado é gerado pela camada Argon2id da Fase 2B.2. Geração de tokens
e cálculo SHA-256 para tokens pertencem a implementações posteriores, conforme
[AUTH.md](AUTH.md).
