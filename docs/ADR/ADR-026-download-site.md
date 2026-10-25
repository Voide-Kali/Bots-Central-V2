# ADR-026: Site de download e instaladores sem terminal

Status: **proposto em 2026-10-24**. Pedido do Voide: a pessoa entra no site, baixa o instalador do
seu sistema, abre, e o agente se instala — sem digitar comando no terminal. Primeiro alvo:
Linux e macOS. Windows fica para depois (exige portar o agente).

## Contexto

Hoje instalar o agente exige clonar o repositorio e rodar `install-linux.sh`/`install-macos.sh` no
terminal, passando a URL do servidor e colando o codigo de pareamento no prompt. Isso e fonte de
erro (URL errada) e afasta quem nao usa terminal. O objetivo e uma pagina estilo "download":
cartoes por sistema/arquitetura, a pessoa baixa um instalador que, ao abrir, instala e pede o
codigo de pareamento numa janela grafica.

## Decisao

1. **Pagina de download gerada, servida em `/baixar`.** Um script de release cross-compila o
   agente, monta um instalador por plataforma, calcula o SHA-256 de cada um e **gera** uma pagina
   estatica (`index.html`) listando os downloads e seus checksums. A pagina e gerada junto com os
   arquivos, entao o checksum sempre bate. Servida pelo Caddy em `/baixar` (publico dentro da
   tailnet; ver item 5).
2. **O instalador e o arquivo que a pessoa baixa.** Ao abrir, ele instala o agente e configura o
   servico (systemd no Linux, LaunchAgent no macOS), igual aos instaladores atuais — reaproveita
   `install-linux.sh`/`install-macos.sh`, so trocando a entrada do codigo.
3. **Codigo de pareamento por janela grafica, nao embutido.** O instalador pergunta o codigo numa
   janela (`zenity`/`kdialog` no Linux, `osascript` no macOS), com fallback para o terminal se nao
   houver ambiente grafico. **Nao** embutimos o codigo no arquivo baixado: o codigo de pareamento
   dura 5 min e expiraria antes de a pessoa rodar. A pessoa gera o codigo no painel ("Adicionar
   computador") e cola na janela. Pareamento, aprovacao e fingerprint continuam exatamente como
   sao hoje — **nenhum poder novo, nenhum protocolo novo**.
4. **Integridade sem assinatura paga: checksum publicado.** Sem conta de desenvolvedor Apple nem
   certificado Windows, o instalador nao e assinado, entao o SO mostra um aviso de "desenvolvedor
   nao identificado" na primeira vez (a pessoa clica em "abrir mesmo assim"). Para garantir que o
   arquivo nao foi adulterado, o painel/pagina mostram o **SHA-256** de cada download, e o arquivo
   so e servido pelo proprio servidor Aval por HTTPS (Tailscale). Assinatura/notarizacao fica como
   melhoria futura, se houver certificado.
5. **Pagina publica, enrolamento ainda fechado.** `/baixar` nao exige login (so a tailnet alcanca),
   porque e so download de binario. Isso **nao** enfraquece a seguranca: o instalador e inutil sem
   um codigo de pareamento valido, que so o dono gera logado no painel, e todo dispositivo novo
   ainda entra como "pendente" ate o dono aprovar comparando o fingerprint.
6. **Binarios nao vao para o repositorio.** O script de release gera os binarios, instaladores e a
   pagina em uma pasta servida (`deploy/server/downloads/`, fora do git). O repositorio guarda o
   **script** e os **modelos** de instalador, nao os artefatos (regra "nao commitar binarios").

## Plataformas (primeiro alvo)

- macOS Apple Silicon (`darwin/arm64`) e Intel (`darwin/amd64`).
- Linux x86-64 (`linux/amd64`) e ARM64 (`linux/arm64`), para Debian/Ubuntu/Kali.
- Windows: **fora do primeiro alvo** — o agente nao tem coletor de telemetria nem servico para
  Windows; e um porte a parte.

## Consequencias

- A pessoa instala com downloads e cliques, colando o codigo numa janela; o terminal deixa de ser
  necessario no caminho comum. Resta o aviso de SO (sem assinatura), mitigado por checksum.
- O `.pkg` do macOS precisa ser montado em um Mac ou em CI com runner macOS (o `pkgbuild` e so do
  macOS); o container de build Linux produz os binarios e o `.deb`/instalador Linux. Ate ter o
  `.pkg`, o macOS usa um instalador por script (`.command`) que abre uma janela — melhoria para
  um `.pkg` real depois.
- Nenhuma mudanca no protocolo assinado, na identidade, na aprovacao ou na auditoria. A unica
  superficie nova e servir arquivos em `/baixar`, coberta por checksum + exposicao so na tailnet.

## O que NAO entra

- Assinatura/notarizacao paga (Apple/Windows) — futuro, se houver certificado.
- Windows — porte do agente, decisao a parte.
- Embutir credencial/codigo no instalador — rejeitado (expira; e vazaria se o arquivo circular).
