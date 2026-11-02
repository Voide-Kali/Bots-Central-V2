# ADR-033: Backups do banco cifrados (age)

Status: **aceito em 2026-10-31**. Correcao de risco apontado em revisao de seguranca (dumps em texto
claro retem dados "apagados").

## Problema

O `backup.sh` fazia `pg_dump` sem cifrar e guardava os dumps por ate 14 dias. O dump inclui a tabela
`command_payloads`, que guarda os bytes dos arquivos enviados pelo agente. Logo, apagar um payload do
banco apos a entrega **nao** o remove das copias ja feitas: quem obtivesse acesso ao disco de backup
poderia ler arquivos e dados de conta. O proprio THREAT_MODEL prevê backups cifrados; o procedimento
nao fazia isso.

## Decisao

Cifrar cada dump com **age**, para uma chave publica (destinatario) cuja **chave privada fica FORA do
servidor**. Assim, uma copia do disco de backup nao pode ser lida sem a chave privada.

- **`backup.Dockerfile`**: imagem do backup = `postgres:17-alpine` + `age` (apk). O serviço `backup`
  no compose passa a `build` dessa imagem.
- **`backup.sh`**: `pg_dump --format=custom | age -r "$BACKUP_AGE_RECIPIENT" -o arquivo.dump.age`. O
  dump nunca toca o disco em texto claro (vai direto por pipe pro age). Exige
  `BACKUP_AGE_RECIPIENT`; sem ele, o serviço falha de proposito (nao grava texto claro). Retencao de
  14 dias passa a casar `*.dump.age`. Dumps `.dump` antigos (de antes da cifragem) **nao** sao
  apagados automaticamente — o script avisa pra remover a mao com seguranca (`shred -u`), pra nao
  destruir a unica copia antes de existir um `.age` bom.
- **`restore-backup.sh`**: `age -d -i chave-privada | pg_restore` (como o owner, porque restaurar faz
  DDL). A chave privada e trazida so na hora e levada embora depois.
- **`generate-env.sh`**: documenta gerar o par com `age-keygen -o aval-backup-key.txt`, guardar a
  privada fora do servidor e colar a publica em `BACKUP_AGE_RECIPIENT`.

## Consequencias

- Uma copia do disco de backup, sozinha, nao abre os dumps. A confidencialidade dos payloads e dados
  de conta nas copias passa a depender da chave privada, que nao fica no servidor.
- Restaurar exige a chave privada. Se ela for perdida, os backups ficam irrecuperaveis — por isso ela
  tem que ser guardada com cuidado (e vale mais de uma copia segura).
- `age` entra na imagem do backup (build num host com acesso ao registry; o servico segue na rede
  interna, sem saida pra internet).
- Em servidor ja no ar: gerar o par, pôr a publica no `.env`, `docker compose up -d --build backup`, e
  depois apagar com `shred` os dumps `.dump` antigos em texto claro.

Validado com Postgres real: `pg_dump | age` gera saida cifrada (cabecalho age, nao texto claro);
`age -d -i chave | pg_restore` restaura os dados intactos; e decifrar com uma chave errada falha.
