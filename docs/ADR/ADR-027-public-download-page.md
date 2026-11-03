# ADR-027: Pagina de download publica (so /baixar), via Tailscale Funnel

Status: **proposto em 2026-10-26**. Pedido do Voide: deixar o site de download acessivel a
qualquer pessoa, nao so a quem esta na tailnet. Decisao tomada: expor **apenas** a pagina de
download; o painel e a API continuam privados.

## Contexto

O servidor Aval e exposto so pela Tailscale (ADR do modelo de seguranca): nada publicado na
internet. Isso protege o painel e a API, que controlam os computadores do dono. Mas tambem faz o
site de download (`/baixar`, ADR-026) so abrir para quem esta na tailnet. O Voide quer que outras
pessoas consigam baixar o instalador.

Abrir o servidor inteiro para a internet foi avaliado e **recusado**: exporia a tela de login, a
API e o controle dos computadores a ataque de qualquer um, derrubando o ponto central do projeto.

## Decisao

Expor **somente** a pagina de download, por um caminho separado e sem controle:

1. **Servidor de download dedicado, so leitura estatica.** Um container proprio (`downloads`)
   serve **apenas** a pasta de downloads (os instaladores + a pagina gerada), sem nenhum proxy
   para a API/backend. Ele publica so em `127.0.0.1:8081` no tropa (nao na LAN, nao no IP da
   tailnet) — so o proprio host o alcanca.
2. **Tailscale Funnel expoe so esse caminho.** `tailscale funnel --set-path=/baixar
   http://127.0.0.1:8081` torna publico apenas `https://<host>.ts.net/baixar`, apontando para o
   servidor de download. O painel e a API seguem no Caddy ligado ao IP da tailnet, **nunca**
   no Funnel — continuam privados.
3. **Nada de controle fica publico.** O que vai para a internet e so: a pagina HTML e os arquivos
   de instalador. Sem login, sem API, sem endpoints de dispositivo.
4. **Enrolamento continua fechado.** Baixar o instalador nao da poder nenhum: para parear, a
   pessoa precisa de um codigo gerado no painel (privado) pelo dono, e todo dispositivo entra como
   "pendente" ate o dono aprovar comparando o fingerprint. Um instalador baixado por um estranho
   e inutil sem o codigo.
5. **Integridade.** A pagina mostra o SHA-256 de cada arquivo; os instaladores nao sao assinados
   (aviso do SO na 1a vez), como ja previsto no ADR-026.

## Risco aceito

A superficie publica nova e: a existencia do host (nome `.ts.net`), a pagina estatica e os
binarios de instalador. Risco baixo: conteudo estatico, sem entrada de dados, sem controle; o
binario e inutil sem o codigo de pareamento do painel privado. Mitigacoes: Funnel so no caminho
`/baixar`, servidor de download isolado (sem acesso a API/db), checksums publicados. O painel e a
API **nao** mudam de exposicao.

### Correcao de isolamento (2026-10-26)

A primeira correcao do 502 (#76) pos o container `downloads` na rede `egress`, que ele
compartilhava com `backend`, `telegram` e `ollama` — um comprometimento do servidor estatico
alcancaria a API e o `ollama` (sem autenticacao) pela rede, contrariando "sem acesso a API/db"
acima. Corrigido: o `downloads` fica numa rede bridge dedicada (`downloads_net`), so dele. Uma
bridge normal publica a porta no host do mesmo jeito (o que faltava na rede `internal: true`), mas
sem dar alcance aos outros servicos. O `db` ja estava isolado (so `internal`). O container de
download nao faz conexao de saida: so serve arquivos locais.

## Operacao (no tropa)

```
# 1) Habilitar HTTPS e Funnel para a tailnet, uma vez, no admin da Tailscale
#    (DNS/HTTPS ligado; nodeAttrs com "funnel" para este host).
# 2) Subir o servidor de download (ja incluso no compose):
cd ~/aval/deploy/server && docker compose up -d downloads
# 3) Expor so /baixar publicamente:
sudo tailscale funnel --bg --https=443 --set-path=/baixar http://127.0.0.1:8081
tailscale funnel status
```

Para desligar o acesso publico a qualquer momento: `sudo tailscale funnel --https=443 --set-path=/baixar off`.

## O que NAO entra

- Expor painel ou API publicamente (recusado).
- Assinatura paga dos instaladores (futuro).
- Observacao: a interacao exata do Funnel com o Caddy do painel (ambos no mesmo hostname) precisa
  ser validada no ambiente do Voide; se houver conflito de porta/hostname, o ajuste e de operacao
  (configuracao do Funnel), nao de codigo.
