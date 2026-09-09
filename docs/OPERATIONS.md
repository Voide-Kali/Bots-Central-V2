# Infraestrutura e operação

## Escopo atual

O Compose deste repositório é o runtime de desenvolvimento da foundation: backend,
migration one-shot e PostgreSQL. Não há deploy automático, container de frontend ou
orquestrador de produção nesta rodada.

Docker requer `sudo` no host. Não adicione usuários ao grupo `docker`, não execute
`docker compose down -v` e não carregue `.env` com `source`. O Compose lê suas variáveis
normalmente; nunca imprima `DATABASE_URL`, senhas ou outras variáveis de segredo durante
diagnóstico.

O banco não possui `ports:` e está em uma rede interna exclusiva. O backend publicado
para desenvolvimento está ligado somente a `127.0.0.1:8000`.

## CI

O workflow `.github/workflows/ci.yml` é executado em `push` e `pull_request`, com a
permissão mínima `contents: read`; ele não referencia `secrets` nem configura deploy.

| Job | Quando executa trabalho | Validação |
| --- | --- | --- |
| `backend` | Sempre | Instala o lock Python, Ruff, Mypy, Pytest com PostgreSQL efêmero e `pip-audit`. |
| `frontend` | Quando `frontend/package.json` existir | Exige `frontend/package-lock.json`, roda `npm ci`, lint, typecheck, testes e build. |
| `agent` | Quando `agent/go.mod` existir | `gofmt` sem alterações, `go vet ./...` e `go test ./...`. |
| `secrets` | Sempre | Gitleaks em todo o histórico disponível no checkout. |

Os jobs de frontend e agent detectam a presença do track depois do checkout. Isso é
necessário porque a função `hashFiles` não é permitida em condicionais de job pelo
GitHub Actions. Enquanto os diretórios não existirem, os jobs terminam sem executar
toolchain. Quando o frontend for adicionado, ele deve fornecer os scripts npm `lint`,
`typecheck`, `test` e `build`, além do lockfile npm.

Builds de PR não confiável recebem apenas o `GITHUB_TOKEN` de leitura configurado pelo
workflow; checkout não persiste credenciais Git. Não adicione secrets, environments de
produção, `pull_request_target` ou passos de deploy a esses jobs.

## Health e readiness

`GET /api/v1/health` é o contrato atual de readiness: somente `status: "ok"` com
`database: "connected"` é pronto para tráfego. O endpoint continua respondendo HTTP
200 também no estado degradado, portanto um probe não deve tratar apenas o código HTTP
como sinal de disponibilidade.

O healthcheck do serviço `backend` valida ambos os campos; o do PostgreSQL continua
usando `pg_isready`. O backend só inicia após o término bem-sucedido da migration, e a
migration só inicia depois de o banco ficar saudável.

Para validar o modelo de Compose sem expandir variáveis de ambiente nem mostrar
segredos, use:

```bash
sudo docker compose config --no-interpolate --quiet
```

Essa verificação não inicia serviços nem aplica migrations. Não use o PostgreSQL de
testes compartilhado para migrations paralelas.

## Containers e redes

Backend e migration já executam como o usuário não privilegiado definido na imagem.
No Compose, ambos agora usam filesystem raiz somente leitura, `/tmp` temporário com
`noexec,nosuid,nodev`, `no-new-privileges` e todas as capabilities removidas. O banco
usa volume persistente e `no-new-privileges`. Ele remove todas as capabilities padrão e
readiciona somente `CHOWN`, `DAC_OVERRIDE`, `SETGID` e `SETUID` durante o bootstrap do
entrypoint oficial: elas permitem percorrer/ajustar um `PGDATA` novo ou preexistente e
trocar de root para `postgres`. O servidor PostgreSQL inicia após essa troca, sem
privilégios de root. Nenhum serviço é privilegiado.

## Validação host-side do PostgreSQL

A validação de Compose no host passou com `sudo docker compose config --no-interpolate
--quiet`. Um smoke test isolado da imagem `postgres:17-alpine`, com volume novo e
credenciais temporárias, também passou: `initdb`, criação do banco, reinicialização
interna do entrypoint, `pg_isready`, healthcheck e conexões finais concluíram com
sucesso. O projeto, volume e credenciais temporários foram removidos após o teste.

O drop de privilégios foi confirmado no runtime: PID 1 e o processo PostgreSQL final
executaram como UID 70 (`postgres`), nunca como root. A inspeção de runtime confirmou
`CapDrop=[ALL]`, `CapAdd=[CAP_CHOWN, CAP_DAC_OVERRIDE, CAP_SETGID, CAP_SETUID]` e
`SecurityOpt=[no-new-privileges:true]`.

Durante o bootstrap, os `chmod` de `PGDATA` e `/var/run/postgresql` podem registrar
`Operation not permitted`, pois `CAP_FOWNER` não é concedida. Esses avisos são tolerados
no conjunto atual: não impediram o ajuste posterior de `PGDATA` por `initdb`, o socket,
o healthcheck, o drop de privilégios nem a operação normal. Não adicione `CAP_FOWNER`
somente para suprimir esses avisos; reavalie apenas diante de necessidade funcional ou
de segurança demonstrada.

A rede `database` é interna e é compartilhada apenas por backend, migration e banco.
A rede `app` permite o tráfego de saída que o backend pode precisar para SMTP; um proxy
web futuro deve se conectar a ela, nunca à rede `database`.

## Plano same-origin de produção

A opção mínima aprovada para a futura web é um único reverse proxy leve, configurado no
ambiente de produção, que termine TLS, sirva os artefatos estáticos em `/` e encaminhe
`/api/` para o backend. Assim browser e API permanecem na mesma origem e CORS continua
desabilitado. PostgreSQL permanece sem porta pública e acessível somente pela rede de
dados.

Antes de introduzir esse proxy, a configuração deve estabelecer uma identidade de peer
estável para ele e definir `TRUSTED_PROXY_IP` para **esse IP exato**. Não assuma que uma
porta Docker publicada preserva `127.0.0.1` como o endereço que o backend observa; valide
o peer dentro do runtime. O proxy deve remover qualquer `X-Forwarded-For` recebido do
cliente e emitir exatamente um único `X-Forwarded-For` com o endereço remoto do cliente.
Não use cadeia multi-hop.

O comando de produção do backend deve continuar contendo `--no-proxy-headers`. Não
habilite parsing automático de headers pelo Uvicorn: a aplicação conserva a política
fail-closed para o peer confiável e para o único XFF.

## Checklist de validação de mudança de infra

1. Verifique a sintaxe YAML do workflow e execute `sudo docker compose config --no-interpolate --quiet`.
2. Confirme que não há `privileged: true` nem porta publicada para `db`.
3. Confirme que o Dockerfile ainda contém `--no-proxy-headers`.
4. Execute os testes de health e proxy do backend sem migrations concorrentes no banco compartilhado.
5. Revise o diff e o scanner de segredos; não registre URLs de banco ou valores de ambiente.
