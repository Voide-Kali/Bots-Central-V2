# Database Foundation — Fase 2B.1

## Escopo

Esta fase adicionou o armazenamento persistente consumido por fluxos de autenticação.
As Fases 2B.2 e 2B.3 agora usam este schema para hashing de senha e registro interno.
Não há endpoint, emissão de token, login, recuperação ou Security Gate.

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

As chaves estrangeiras usam `RESTRICT`: credenciais e histórico de token não são
apagados em cascata por acidente. Identificadores são UUIDs v4 gerados no servidor.

## Invariantes e índices

- `users.security_version` e `sessions.security_version` não podem ser negativos.
- `user_emails.email_canonical` é globalmente único e não vazio; há índice para
  `user_id` e índice parcial único que permite no máximo um e-mail principal por usuário.
- `password_credentials.user_id` é chave primária, portanto há no máximo uma
  credencial de senha atual por usuário.
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

`password_hash`, `token_digest` e metadados de contexto são dados sensíveis. O schema
não possui campo de token plaintext, token bruto ou segredo. Plaintext de access/refresh
token só poderá existir durante emissão e verificação futuras, nunca em persistência,
URLs, `repr` ou logs. `repr` dos modelos omite hashes, digests e metadados.

O hash de senha armazenado é gerado pela camada Argon2id da Fase 2B.2. Geração de tokens
e cálculo SHA-256 para tokens pertencem a implementações posteriores, conforme
[AUTH.md](AUTH.md).
