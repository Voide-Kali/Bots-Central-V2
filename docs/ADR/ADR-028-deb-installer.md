# ADR-028: Instalador Linux em .deb (clique duplo, sem terminal)

Status: **aceito em 2026-10-26**. Pedido do Voide: ao baixar o instalador Linux, a pessoa so
clicar e funcionar — o `.run` auto-extraivel (ADR-026) abria num editor de texto mostrando "um
monte de codigo baguncado" e nao executava.

## Contexto

No Linux, um arquivo `.run`/`.sh` baixado perde o bit de execucao (o navegador remove) e, no clique
duplo, o ambiente grafico abre num editor de texto em vez de rodar. Nao da pra consertar mantendo
`.run`. O formato nativo de "clicar e instalar" no Debian/Ubuntu/Kali/Raspberry Pi OS (todo o
publico do projeto) e o pacote **`.deb`**: o clique duplo abre o instalador grafico do sistema
(GNOME Software / apt / gdebi), a pessoa clica em **Instalar** e digita a senha uma vez.

## Decisao

O site de download passa a servir, para Linux, pacotes `.deb` (`amd64` e `arm64`) no lugar dos
`.run`. macOS continua com `.command` e, quando gerado num Mac, o `.pkg` (ADR-026).

1. **Pacote `.deb` gerado no deploy** por `deploy/release/build-deb.sh`, chamado por
   `build-downloads.sh`. O binario e cross-compilado (Go, estatico `CGO_ENABLED=0`) e a URL do
   servidor e assada no `config.json` do pacote.
2. **Conteudo do pacote:** binario em `/usr/bin/aval-agent`, `config.json` assado, a unit systemd
   endurecida (a mesma do repo, so com o caminho ajustado para `/usr/bin`), os drop-ins de
   privilegio por acao (webcam/scan/journal) e a regra polkit de `lock_screen` — todos decididos
   em tempo de build pelas acoes assadas.
3. **`postinst` nao inicia o servico** — so cria o usuario de sistema `aval-agent`, as pastas
   (`/var/lib/aval-agent`, `/srv/aval-compartilhado`) e recarrega o systemd. O agente so sobe apos
   o pareamento. Dependencias (`zenity`, e `nmap`/`fswebcam` conforme as acoes) sao resolvidas pelo
   apt/instalador grafico (campos `Depends`/`Recommends`).
4. **Pareamento e um passo grafico separado:** o pacote instala o item de menu **"Parear Aval"**
   (`/usr/bin/aval-parear`), que abre uma janela (zenity/kdialog; cai pro terminal se nao houver
   GUI) pedindo o codigo do painel, re-eleva via `pkexec` (ou `sudo`), registra o dispositivo e so
   entao `systemctl enable --now aval-agent`. O codigo vai por stdin — nunca em argv, historico ou
   arquivo.
5. **Remocao limpa:** `prerm` para/desabilita o servico; `postrm purge` remove estado, config e o
   usuario de sistema.

## Por que nao outras opcoes

- **AppImage / `.run` com bit +x:** o clique duplo tambem nao roda download sem `chmod` manual, e
  o GNOME nao executa. Nao resolve o pedido.
- **Repositorio apt proprio (`apt install aval-agent`):** mais limpo para updates, mas exige o
  usuario rodar comando no terminal e configurar a chave/fonte — o oposto do pedido. Fica como
  evolucao futura.

## Risco aceito

Pacote `.deb` nao assinado (igual ao `.run`/`.command` do ADR-026): o instalador grafico pode
avisar que a origem nao e confiavel na 1a vez. A pagina publica o SHA-256 de cada arquivo para
conferencia. O `.deb` vem do proprio servidor do dono, via Funnel so em `/baixar` (ADR-027).
