# ADR-029: Landing animada na pagina publica /baixar

Status: **aceito em 2026-10-26**, **revisado em 2026-10-31** (troca do design — ver "Revisao" no fim).
Pedido do Voide: a pagina publica, antes do download, explicar o que o sistema e/faz, com visual
melhor e animacao 3D, e ter contato com quem criou.

## Contexto

A `/baixar` (ADR-026/027) era so uma lista de instaladores. O Voide quer uma landing de verdade:
hero animado, explicacao do Aval, como funciona, seguranca, downloads e contato. E a UNICA parte
publica do sistema (Funnel so em `/baixar`; painel e API seguem privados).

## Decisao

1. **Site estatico em `deploy/release/site/`** (`index.html`, `styles.css`, `app.js`,
   `three.min.js`). Direcao visual escolhida: escuro com acento neon (dark techy 3D).
2. **Hero 3D** com uma rede de particulas (Three.js), como pano de fundo do titulo. Degrada com
   graca: sem WebGL ou com `prefers-reduced-motion`, o fundo CSS fica e o resto da pagina funciona.
3. **Three.js hospedado no proprio servidor** (`three.min.js`, UMD, versao 0.160.1 vinda do npm),
   nunca de CDN externo — respeita a CSP (`default-src 'self'`) e o AGENTS.md. Todo o JS/CSS e
   servido de `'self'`; nenhuma chamada externa. (Three.js e dependencia de terceiros, texto
   minificado; nao e binario/segredo.)
4. **Secoes**: o que e, como funciona (4 passos), seguranca, baixar (cards gerados), contato. O
   contato e so um link para o GitHub (`Voide-Kali`) — sem e-mail pessoal em pagina publica, e sem
   formulario (um form exigiria endpoint publico, contra o isolamento do ADR-027).
5. **Cards de download injetados no build.** `build-downloads.sh` copia os assets e injeta os cards
   (nomes dos arquivos + SHA-256, conhecidos so no build) no lugar do marcador `<!--DOWNLOAD_CARDS-->`
   com `awk` (sem dependencia de python no servidor). Instaladores e checksums seguem iguais.

## Consequencias

- A pagina publica passa a explicar o sistema e a reforcar a mensagem ("nada sem o seu aval") antes
  do download. Nenhuma nova superficie dinamica: continua 100% estatica, servida pelo container de
  download isolado.
- `three.min.js` (~650 KB) entra no repositorio como dependencia vendorizada, para o build nao
  depender de rede no deploy. Atualizar a versao e trocar o arquivo e a referencia.
- A CSP e o Caddy nao mudam: tudo e `'self'` (scripts, estilos, sem `connect-src` externo).
- Nenhuma mudanca de seguranca, auth, identidade ou protocolo. So a camada publica de apresentacao.

## Revisao (2026-10-31): design proprio do Voide

O Voide fez a sua propria pagina de apresentacao (um artefato) e pediu para usa-la no lugar da
primeira. Trocamos o conteudo de `deploy/release/site/`, mantendo o mesmo encaixe de build e CSP:

1. **Novo visual**, direcao "type and nothing else" por cima do pedido do Voide (escuro, 3D,
   tipografia grande). Tres destaques: o **selo 3D "visto"** (disco carimbado feito so com camadas
   CSS, sem WebGL), um campo onde da pra **escrever um pedido** e ver a regra do bot reconhecer a
   acao, e a **tabela da pesquisa de prompt injection** (0% de execucao).
2. **Sem Three.js.** O hero 3D agora e CSS puro, entao `three.min.js` saiu do repo. Entram, como
   assets do proprio design: 4 fontes (`fonts/*.woff2`, Bebas Neue + EB Garamond, vindas do npm) e 4
   screenshots do sistema (`img/*.jpg`, dados de exemplo). `styles.css` saiu — o CSS e inline no
   `index.html` (a CSP permite `style-src 'unsafe-inline'` no `/baixar`).
3. **Scripts em `'self'`, nunca inline.** A CSP do `/baixar` e `default-src 'self'` (sem
   `'unsafe-inline'` para script). O design vinha com `<script>` inline, entao o JS foi separado em
   `boot.js` (marca `js` antes do paint) e `app.js` (interacoes). Nenhum inline script sobra —
   validado com um Chromium headless servindo a pagina com a CSP real: zero violacao, selo/fontes/
   demos/cards OK.
4. **Downloads dentro do "Como funciona".** O passo 1 ("baixe e instale o agente") agora mostra os
   cards de download reais (um por sistema, com SHA-256) no lugar de um comando de terminal. Mesmo
   marcador `<!--DOWNLOAD_CARDS-->` e mesma injecao por `awk`; `build-downloads.sh` so passou a
   copiar `boot.js`, `app.js`, `fonts/` e `img/` (antes: `styles.css`, `app.js`, `three.min.js`).
5. **Contato na pagina** (decisao do Voide, revertendo o ponto 4 original): o design publica o e-mail
   do projeto `aval.app.br@gmail.com` e o `Telegram @aval_sistema_bot`, alem do GitHub. E um e-mail
   dedicado do projeto (nao pessoal) e nenhum formulario/endpoint novo — segue sem superficie
   dinamica, 100% estatico.

Nada de auth, identidade, protocolo ou isolamento muda. A `/baixar` continua a unica parte publica.
