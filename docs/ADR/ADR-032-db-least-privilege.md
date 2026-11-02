# ADR-032: Papel de banco com menos privilegio para backend e bot

Status: **aceito em 2026-10-31**. Correcao de risco apontado em revisao de seguranca (papel de
banco administrativo usado pela aplicacao).

## Problema

No `compose.yaml`, `backend`, `telegram` e `migration` conectavam no Postgres com a mesma
credencial `POSTGRES_USER`. Na imagem oficial do Postgres esse usuario inicial e **superusuario** e
dono de todas as tabelas. Consequencia: uma invasao do backend ou do bot herda poder administrativo
no banco e pode, por exemplo, **desabilitar ou dropar o trigger append-only da auditoria**
(`audit_events_no_rewrite`, migration 0010) e reescrever o historico. O trigger protege contra
UPDATE/DELETE comuns, mas nao contra o proprio papel administrativo que a aplicacao usava. Isso
tambem contraria o principio de menor privilegio.

## Decisao

Separar os papeis:

- **`POSTGRES_USER` (owner/superusuario):** usado **so** pela `migration` (precisa de DDL) e dono das
  tabelas. Tambem segue sendo usado pelo `backup` (o `pg_dump` precisa ler tudo; servico interno, sem
  entrada da internet).
- **`APP_DB_USER` (novo, ex.: `aval_app`):** usado por `backend` e `telegram`. `NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOINHERIT`, nao e dono de nada. Recebe so:
  - `SELECT/INSERT/UPDATE/DELETE` nas tabelas e `USAGE,SELECT` nas sequences;
  - em `audit_events`, **so `SELECT` e `INSERT`** (REVOKE UPDATE/DELETE) — pode registrar e ler, nunca
    reescrever;
  - `ALTER DEFAULT PRIVILEGES` para que tabelas de **migrations futuras** (criadas pelo owner) herdem
    os mesmos grants automaticamente;
  - `REVOKE CREATE ON SCHEMA public` — nao pode criar objetos (nao vira dono de nada).

Como o papel nao e dono das tabelas nem superusuario, **nao consegue** `ALTER TABLE ... DISABLE
TRIGGER`, `DROP TRIGGER`, nem nenhum DDL. A integridade da auditoria passa a resistir a um
comprometimento do backend/bot.

### Como entra no deploy

1. `generate-env.sh` passa a gerar `APP_DB_USER=aval_app` e `APP_DB_PASSWORD=$(rand)` no `.env`.
2. `deploy/server/sql/app-role.sql` cria/atualiza o papel e aplica os grants. E **idempotente** (usa
   `\gexec` para criar so se faltar e reassenta flags/senha e grants a cada execucao).
3. `deploy/server/setup-app-role.sh` roda esse SQL no container `db` como `POSTGRES_USER`. Rodar uma
   vez (e de novo e inofensivo) **antes** de subir `backend`/`telegram`:
   ```
   cd deploy/server
   ./setup-app-role.sh
   docker compose up -d backend telegram
   ```
4. `compose.yaml`: `backend` e `telegram` usam `DATABASE_URL` com `APP_DB_USER`; `migration` mantem
   `POSTGRES_USER`.

## Consequencias

- Um backend/bot comprometido nao consegue mais mexer na auditoria nem rodar DDL. Menor privilegio
  cumprido para as superficies expostas.
- Passo extra de deploy (`setup-app-role.sh`), idempotente e documentado. Em servidor ja no ar: rodar
  o script, depois `docker compose up -d backend telegram`; a `migration` segue igual.
- `backup` continua como `POSTGRES_USER` (precisa ler tudo; interno, sem entrada publica). Reduzir
  isso a um papel so-leitura (`pg_read_all_data`) fica para um passo futuro, se quisermos.
- A senha do papel de aplicacao e mais um segredo no `.env` (nunca versionado), ao lado da senha do
  superusuario.

Validado com um Postgres real (cluster descartavel): o papel faz DML nas tabelas, escreve e le
auditoria, mas tem UPDATE/DELETE de auditoria negados, e nao consegue DISABLE/DROP do trigger, DROP/
ALTER/CREATE de tabela; tabelas criadas depois herdam os grants; reaplicar o SQL e idempotente.
