# ADR-034: Site na raiz, painel em /painel

Status: **aceito em 2026-11-03**. Reorganiza as URLs públicas para uma hierarquia consistente.

## Problema

A raiz `/` servia o **painel React** (tela de login), e a página bonita de apresentação ficava em
`/baixar`. Quem abria `https://aval.<tailnet>.ts.net/` caía numa tela de login, não no site. O
inverso do padrão de produto, e as sub-URLs ficavam inconsistentes (políticas dentro de `/baixar`).

## Decisao

Inverter: a landing passa a ser a raiz; o painel e as políticas penduram embaixo dela.

| URL | Conteúdo |
|---|---|
| `/` | Landing (apresentação + botões de download) |
| `/privacidade`, `/termos` | Páginas legais (saíram de dentro de `/baixar`) |
| `/painel/*` | Painel React (gerenciar computadores) — antes na raiz |
| `/baixar/*` | **Só os arquivos** de instalador (.deb/.command + .sha256) |
| `/api/*`, `/email-verification` | Backend (sem mudança) |

### Como fica montado

- **Caddyfile:** `handle /painel/*` serve o SPA (root `/srv`, `try_files {path} /painel/index.html`);
  `handle_path /baixar/*` serve os arquivos (root `/srv/site/baixar`); o `handle` final serve o site
  na raiz (root `/srv/site`). `redir /painel /painel/` e `redir /baixar /` arrumam os caminhos nus.
  Cada caminho recebe a CSP certa: o site com `style-src 'unsafe-inline'` (estilos inline da
  landing); o painel com a CSP estrita de app.
- **Painel sob subpath:** Vite com `base: "/painel/"` (assets em `/painel/assets/*`) e o roteador
  próprio (`src/app/navigation.ts`) virou consciente do prefixo — um `BASE = "/painel"` que ele tira
  da URL ao ler a rota e põe ao navegar; `appHref()` monta os `<a href>`. As rotas internas
  (`/login`, `/devices`…) continuam root-relative no código.
- **web.Dockerfile:** copia o `dist` para `/srv/painel` (antes `/srv`).
- **compose:** o `web` monta `./downloads:/srv/site` (antes `/srv/baixar`). O serviço `downloads`
  legado (ADR-027, interno em 127.0.0.1:8081) segue em `/srv/baixar`, intocado — hoje redundante com
  o `web`; pode ser removido numa limpeza futura.
- **build-downloads.sh:** a landing + políticas + assets vão pra raiz da saída; os instaladores pra
  `downloads/baixar/`. Os cards de download apontam pra `baixar/<arquivo>`.
- **Backend:** o e-mail de verificação passa a linkar `{origin}/painel/verify` (a rota é do painel).
  O link inerte de `/email-verification` continua no backend, na raiz.

## Consequencias

- Quem abre a raiz vê o site, não a tela de login — o esperado. O painel tem um lar próprio
  (`/painel`), coerente com o comando `/painel` do bot.
- Os links de download ficam estáveis em `/baixar/<arquivo>`; a antiga URL de página `/baixar`
  redireciona pra `/`.
- Mudança de rota, não de segurança: a mesma origem, os mesmos cookies (`path=/` cobre `/painel`),
  a mesma política de CSRF/Origin. Auth, identidade e protocolo não mudam.

Validado com um Caddy real: `/` (landing), `/privacidade`, `/termos`, `/painel/` e seu fallback de
SPA, os assets `/painel/assets/*`, `/baixar/<arquivo>` e os redirects `/baixar`->`/` e
`/painel`->`/painel/`, cada um com a CSP e os headers de segurança corretos. Frontend: 90 testes,
lint, typecheck e build (com a nova base) passam. Backend: ruff, mypy e o teste do link de e-mail
passam.
