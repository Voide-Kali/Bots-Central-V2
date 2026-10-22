# Revisão de segurança — Aval (Bots-Central-V2)

Data: 2026-10-22. Autor: sessão de análise (somente leitura de código; nenhum arquivo de
código foi alterado). Base: branch `feat/telegram-menu-kb`.

Escopo lido: `backend/` (auth, identidade de dispositivo, autorização, revogação, protocolo
assinado JWS/Ed25519, anti-replay por sequência, AbuseController, auditoria, assistente,
ações com aval), `agent/` (identidade, transporte, executor), `deploy/` (Caddy/CSP, Docker
Compose), `docs/ADR/` e `docs/SECURITY_MODEL.md`. Comparação com o sistema antigo em
`/home/claude/kali-bunker-bots` e `docs/LEGACY-INVENTORY.md`.

Este documento não altera nenhuma decisão de segurança. As mudanças em autenticação,
identidade, autorização, revogação, protocolo ou auditoria continuam exigindo ADR e aprovação
do Voide (seção 5).

---

## 1. Modelo de ameaças resumido

**O que o atacante quer:** executar ações no computador do dono (desligar, webcam, cofre,
firewall), ler dados dos dispositivos/telemetria, assumir a conta, ou usar a plataforma como
pivô para a rede de casa.

**Superfícies de ataque e o que cada uma não pode confiar:**

| Superfície | Entrada do atacante | Defesa de desenho |
|---|---|---|
| Internet → backend (via Tailscale) | Qualquer um na tailnet alcança o backend; headers, IDs, origem e tokens são alegações | Exposição só no Tailscale; CORS same-origin; limites de corpo; AbuseController fail-closed; sessões bearer opacas de 10 min |
| Agente comprometido / SO do PC | Executor local adulterado, resultados forjados, pivô | Identidade Ed25519 por dispositivo, revogação, `allowed_actions`, catálogo fechado; o backend não garante integridade de SO comprometido (risco residual aceito, T13) |
| Dispositivo (celular/PC) roubado | Sessão/refresh roubados, comandos com a autoridade do dono | Armazenamento mínimo, prazos curtos, revogação, `security_version` revalidada a cada ação |
| Prompt injection na IA | Nome de dispositivo malicioso, pergunta hostil | IA sem ferramentas; dados cercados em `<dados>`; pior caso = resposta errada, nunca ação (ADR-013) |
| Telegram | Mensagem/botão forjado, chat não vinculado | Só chat privado com `chat.id == from.id`; exige vínculo; botões passam pelas mesmas checagens dos comandos |
| Painel web | XSS, CSRF, clickjacking | Token em memória (não em localStorage); refresh same-origin + `Sec-Fetch-Site`; headers no Caddy; CSP do SPA é uma lacuna (achado M2) |
| E-mail | Caixa comprometida intercepta código de recuperação e de aval | Códigos curtos, vinculados, uso único; **e-mail é a raiz de confiança** e exige 2FA (risco aceito, seção 5) |
| Backup/operador | Leitura de backup, DBA abusivo apaga auditoria | Argon2id + digests; backups cifrados; auditoria append-only (trigger); risco de DBA/root aceito (T18) |

Atacante fora de alcance (aceito): comprometimento total do backend/SO, DBA/root com controle
do PostgreSQL. O desenho busca contenção e revogação, não imunidade.

---

## 2. O que já está bem feito (não mexer)

Pontos sólidos e verificados — preservar como estão:

- **Identidades separadas.** Usuário: Argon2id + sessão opaca no servidor, só digest no banco.
  Dispositivo: Ed25519 gerada no aparelho, aprovada por comparação de fingerprint
  (`backend/app/auth/device_online.py:110`, `:315`). `hmac.compare_digest` no fingerprint.
- **Protocolo assinado com anti-replay.** JWS EdDSA, audiência fixa por finalidade
  (`device_online.py:28-29`, `:115`), exige `aud`+`sub`, limite de 8 KiB. Sequência monotônica
  única compartilhada entre heartbeat e canal de comandos: cada requisição assinada é de uso
  único nos dois endpoints (`device_online.py:405`, `backend/app/devices/commands.py:358-391`).
- **Ação só com segundo fator por e-mail.** Código de 8 dígitos vinculado ao comando por HMAC,
  5 min, 5 tentativas; o código abre exatamente um comando (`commands.py:208-276`). O agente só
  conhece o comando após aprovação, por requisição assinada que consome a sequência.
- **Executor do agente defensivo** (`agent/internal/commands/commands.go`): nome puro validado,
  `filepath.Dir == sharedDir`, `Lstat`, rejeita não-regular (symlink/dir/socket), rejeita
  `Nlink > 1` (hard link), `O_NOFOLLOW`, recheck `os.SameFile`, `LimitReader`. Sem shell.
- **Auditoria append-only na mesma transação da ação** (`backend/app/audit/events.py:36-50`),
  com recusa explícita de chaves que carreguem segredo (`token`, `code`, `password`, `jws`…).
- **AbuseController fail-closed e atômico** (`backend/app/auth/abuse_control.py`): admite todas
  as dimensões ou nenhuma; chaves pseudonimizadas por HMAC próprio; `SQLAlchemyError` →
  `AbuseControlUnavailable` (nega). Políticas por identificador/rede/dispositivo/global.
- **Validação de configuração** (`backend/app/core/config.py`): produção exige origem HTTPS
  não-loopback, SMTP e chave de abuso válida; `DEBUG` proibido em produção; `PUBLIC_ORIGIN` sem
  userinfo/path/query.
- **Isolamento de rede** (`deploy/server/compose.yaml`): rede `internal: true` para db/ollama;
  nada publicado na internet; Caddy liga só no IP do Tailscale; `TRUSTED_PROXY_IP` de salto
  único casado com o Caddy, que ignora `X-Forwarded-For` do cliente.
- **TLS no agente** (`agent/internal/transport/http.go:369`): só HTTPS (http apenas em teste);
  `CheckRedirect` não repassa token/JWS a destino de redirect (`:87`).
- **Assistente sem ferramentas** (`backend/app/assistant/assistant.py`): só snapshot do próprio
  usuário; dados em `<dados>`, nomes limpos (controles removidos, `<`/`>` trocados), pergunta
  limitada a 500 e resposta a 3500 chars; sessão de banco fechada antes da chamada ao modelo.
- **Página de verificação HTML** com CSP própria e `X-Frame-Options: DENY`
  (`backend/app/api/v1/routes/auth.py:987-999`).

Comparado ao sistema antigo, o Aval já corrigiu os erros centrais do Kali Bunker: transporte
por SSH + fila SQLite virou agente Ed25519 com JWS sobre HTTPS; a "confirmação no mesmo chat"
(que o próprio `SECURITY.md` antigo admitia não ser segundo fator —
`kali-bunker-bots/apps/kali-bunker/SECURITY.md:22`) virou código por e-mail (outro canal); a IA
que podia preparar `ssh host comando` (`remote_control.py:1938`) virou IA sem ferramentas; o
token de bot compartilhado e os `.env` espalhados viraram um processo único e segredos no
servidor; o incidente de credencial em PDF virou `gitleaks` no CI.

---

## 3. Riscos encontrados

### Corrigir antes da feira

**M1 — Imagem do Ollama não fixada (`latest`). Severidade: média.**
`deploy/server/compose.yaml:79`: `image: ${OLLAMA_IMAGE:-ollama/ollama:latest}`.
Dependência não fixada: a cada `--build`/pull a versão muda, o que quebra reprodutibilidade e
abre deriva de supply-chain (a imagem roda no servidor de casa, mesmo host do backend e do
banco). O risco direto é contido (rede interna, sem porta publicada), mas o custo de correção é
baixo.
*Recomendação:* fixar por tag + digest (ex.: `ollama/ollama:0.x.y@sha256:…`) no `.env`
(`OLLAMA_IMAGE`) e documentar a atualização consciente. Alinha com o princípio de "testes
reproduzíveis" do projeto.

**M2 — Painel web (SPA) sem Content-Security-Policy. Severidade: média.**
O `deploy/server/Caddyfile` define HSTS, `X-Content-Type-Options`, `X-Frame-Options` e
`Referrer-Policy`, mas **não** define `Content-Security-Policy` para o SPA servido em `/`
(`handle { file_server }`); o `web.Dockerfile` também não injeta CSP, e não há CSP no build do
frontend. O `THREAT_MODEL.md` lista XSS (T11) como ameaça do cliente web, e o access token fica
em memória do SPA — um XSS leria o token e agiria como a vítima.
*Recomendação:* adicionar CSP restritiva ao bloco `header` do Caddy para as respostas do SPA,
no espírito da CSP que a página de verificação já usa (ex.: `default-src 'self'; script-src
'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';
base-uri 'none'; form-action 'self'`). Validar contra o build real do painel (Vite) antes de
apertar. Observação: isto é endurecimento de deploy, não toca o núcleo de segurança; pode ir
por PR de deploy sem ADR.

### Depois da feira

**M3 — Reuso de uma única chave HMAC entre finalidades. Severidade: média (aceito/planejado).**
`ABUSE_CONTROL_HMAC_KEY` serve, com namespaces separados, a três usos: limites de abuso, código
de recuperação de senha e MAC de aprovação de comandos
(`backend/app/devices/commands.py:118` usa `key.pseudonymize("device-command-approval", …)` da
mesma `AbuseControlKey`). A separação por namespace mitiga, mas o vazamento da chave única
compromete os três domínios de uma vez. Já reconhecido em `CURRENT_STATE.md` e o ADR-016 §7
propõe derivar chaves por uso via HKDF (`rate-limit`, `reset-code`, `approval-code`,
`vault-label`).
*Recomendação:* aprovar e implementar a separação por HKDF do ADR-016 §7. É decisão de
protocolo/segredo — ver seção 5.

**L1 — HSTS sem `includeSubDomains`/`preload`. Severidade: baixa.**
`Caddyfile`: `Strict-Transport-Security "max-age=31536000"`. No contexto `*.ts.net` o impacto é
pequeno; incluir as diretivas é endurecimento barato quando/se houver domínio próprio.

**L2 — Sem `Permissions-Policy`. Severidade: baixa.**
O SPA não envia `Permissions-Policy`. Com a foto de webcam prevista (ADR-016) e para reduzir a
superfície, convém negar por padrão no Caddy: `Permissions-Policy: camera=(), microphone=(),
geolocation=()`. O acesso real à webcam é do agente no PC, não do navegador; o header é defesa
em profundidade do painel.

**L3 — Compose de desenvolvimento publica a porta 8000 em todas as interfaces. Severidade:
baixa (apenas dev).**
`compose.yaml:12-13` (raiz) expõe `8000:8000` com `APP_ENV: development` e sem
`ABUSE_CONTROL_HMAC_KEY`, ou seja, com as checagens de produção desligadas. É o arquivo de dev e
não deve ir para a casa (o deploy real é `deploy/server/compose.yaml`). Vale uma nota no arquivo
ou bind em `127.0.0.1:8000:8000` para evitar exposição acidental se alguém rodá-lo num host não
isolado.

**L4 — `openNoFollow` cobre só o componente final. Severidade: baixa (defesa em profundidade).**
`agent/internal/commands/open_unix.go` aplica `O_NOFOLLOW` ao caminho final, e o conjunto
`Lstat` + `Nlink` + `SameFile` fecha o caso do arquivo-alvo. Um atacante local que controlasse
um componente de diretório symlink *acima* da pasta compartilhada poderia redirecionar — cenário
que já exige controle local do FS (fora do modelo). Melhoria opcional: abrir a pasta
compartilhada com `openat`/`O_DIRECTORY` e resolver o nome a partir desse descritor.

Não foram encontrados, nesta leitura, defeitos no núcleo assinado (JWS/sequência), na
autorização por propriedade (`Device.user_id == user_id` em todas as consultas de dispositivo),
na vinculação do código de aprovação ao comando, nem na auditoria. Onde o desenho aceita um
risco, ele está documentado e coerente (seção 5).

---

## 4. Recomendações de endurecimento priorizadas

1. **Fixar a imagem do Ollama** por tag+digest (M1). *Antes da feira.*
2. **CSP no SPA** no Caddy (M2), validada contra o build do painel. *Antes da feira.*
3. **`Permissions-Policy` e HSTS `includeSubDomains`** no Caddy (L1, L2). *Depois.*
4. **Separar as chaves HMAC por HKDF** (M3 / ADR-016 §7). *Depois, via ADR.*
5. **Bind do compose de dev em loopback** ou nota explícita (L3). *Depois.*
6. **Escopo do agente:** manter `allowed_actions` vazio por padrão e `unlock_screen`/`vault_*`
   desligados (ADR-016); cada ação nova entra em PR próprio com testes de recusa (fora do
   catálogo, parâmetro extra, digest trocado, ação não declarada). *Conforme ADR-016 avança.*
7. **Validação de entrada:** manter a disciplina atual (nomes de arquivo por `valid_file_name`,
   `assistant_model` por regex, limites de corpo por rota). Sem ação pendente.
8. **Rotação de segredos:** documentar procedimento de rotação de `ABUSE_CONTROL_HMAC_KEY` e do
   token do bot (hoje o reuso torna a rotação mais sensível — ligado a M3).

---

## 5. Pontos que exigem ADR / decisão do Voide (não mudar sozinho)

Por `SECURITY_MODEL.md` e `AGENTS.md`, mudanças em autenticação, identidade, autorização,
revogação, protocolo do agente ou auditoria exigem ADR e aprovação. Esta análise **não** propõe
alterá-los; apenas registra as decisões em aberto:

- **Aprovar o ADR-016 (ações com aval).** Está "proposto, aguardando aprovação do Voide". Sem
  isso, `power`, `network_scan`, `ban`, `apt_*`, `vault_*`, `webcam_photo` não devem ser
  implementados. Os itens de maior risco (`unlock_screen`, `vault_reveal`) permanecem desligados
  por padrão.
- **Separação de chaves por HKDF (ADR-016 §7 / M3).** Decisão de protocolo/segredo.
- **Confiança na aprovação server-side.** Um servidor comprometido pode criar *e* aprovar
  comandos (o código é verificado no servidor). Aceito hoje; a evolução é aprovação assinada no
  celular e verificada pelo agente. Decisão de arquitetura futura.
- **E-mail como raiz de confiança.** Recupera senha e aprova ações; a caixa precisa de 2FA.
  Decisão de política (documentada em `CURRENT_STATE.md`), não de código.
- **Qualquer mudança no protocolo assinado, na sequência anti-replay ou na auditoria
  append-only** (ex.: L4, tornar a auditoria tamper-proof fora do mesmo PostgreSQL) exige ADR.

---

## Resumo dos achados por severidade

- **Alta:** nenhum.
- **Média:** M1 (Ollama `latest` não fixado — antes da feira), M2 (SPA sem CSP — antes da
  feira), M3 (reuso de chave HMAC única — depois, via ADR-016 §7).
- **Baixa:** L1 (HSTS sem `includeSubDomains`), L2 (sem `Permissions-Policy`), L3 (compose de
  dev publica 8000), L4 (`O_NOFOLLOW` só no componente final — defesa em profundidade).

O núcleo de segurança (identidades separadas, protocolo assinado com anti-replay, ação só com
aval por e-mail, executor do agente, auditoria append-only) está bem construído e não deve ser
mexido fora de ADR.
