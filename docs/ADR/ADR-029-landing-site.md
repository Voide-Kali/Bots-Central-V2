# ADR-029: Landing animada na pagina publica /baixar

Status: **aceito em 2026-10-26**. Pedido do Voide: a pagina publica, antes do download, explicar o
que o sistema e/faz, com visual melhor e animacao 3D, e ter contato com quem criou.

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
