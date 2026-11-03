# ADR-035: backend e telegram nao recebem a senha do dono do banco no ambiente

Status: **aceito em 2026-11-03**. Correcao do achado C1 de revisao de seguranca estatica
(2026-11-03), que estende o ADR-032.

## Problema

O ADR-032 separou os papeis do Postgres: `backend` e `telegram` conectam como o papel restrito
`APP_DB_USER` (pela `DATABASE_URL`), e so a `migration` usa o dono/superusuario. Porem, no
`compose.yaml`, os servicos `backend` e `telegram` recebiam `env_file: .env` — e o `.env` contem
`POSTGRES_PASSWORD`, a senha do dono/superusuario.

Resultado: mesmo conectando como `APP_DB_USER`, esses dois containers tinham a senha do dono exposta
como variavel de ambiente. Execucao de codigo ou comprometimento de qualquer um deles permitiria ler
`$POSTGRES_PASSWORD` e abrir uma segunda conexao como dono — contornando o ADR-032, alterando o
schema e desabilitando ou reescrevendo o trigger append-only da auditoria. A separacao de privilegio
no nivel do banco existia, mas estava anulada no nivel do ambiente do processo.

## Decisao

`backend` e `telegram` deixam de ter a credencial do dono no ambiente. Como o bloco `environment`
vence o `env_file` no Docker Compose, a correcao e local e deterministica: nos dois servicos,
`POSTGRES_PASSWORD` e `POSTGRES_USER` sao sobrescritos para string vazia. A credencial do dono deixa
de ter valor no ambiente desses containers; o app nunca precisou dela (usa `APP_DB_USER` pela
`DATABASE_URL`).

Permanece inalterado:

- `migration` continua usando a credencial do dono (precisa de DDL) via `env_file: .env` — servico de
  vida curta, sem entrada da internet.
- `db` e `backup` recebem a senha do dono por interpolacao `${POSTGRES_PASSWORD}` (nao por
  `env_file`), e seguem como estao.
- Nenhuma variavel que o app realmente usa e removida: a correcao mexe so nas duas credenciais do
  dono, que o app ignora (`extra="ignore"` no `Settings`).

Nao foi usado um `.env` separado para o app porque isso exigiria um novo arquivo de segredos gerado
pelo `generate-env.sh` e quebraria o deploy ja existente (que tem `.env`, sem o novo arquivo) no
primeiro `docker compose up`. A sobrescrita por `environment` corrige o risco sem atrito de deploy:
basta `git pull` e `docker compose up -d`.

## Verificacao

Depois de subir a stack, sem imprimir segredo:

```
# vazio nos servicos do app (valor removido):
docker compose exec backend  sh -c 'test -z "$POSTGRES_PASSWORD" && echo ok-vazio || echo TEM-VALOR'
docker compose exec telegram sh -c 'test -z "$POSTGRES_PASSWORD" && echo ok-vazio || echo TEM-VALOR'
```

Ambos devem imprimir `ok-vazio`. (A `migration`, por ser dono, legitimamente tem o valor.)

## Limite conhecido

A senha do dono continua no `.env` do servidor (necessaria para `db`, `backup` e `migration`) e no
ambiente da `migration` enquanto ela roda. O ganho e tirar essa credencial dos dois processos de vida
longa expostos. Reduzir ainda mais o alcance do papel `APP_DB_USER` (p.ex. `UPDATE` por coluna, sem
`users.role`) e cifragem do volume ativo do Postgres sao itens separados, registrados como
acompanhamento da mesma revisao.
