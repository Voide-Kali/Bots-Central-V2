# ADR-020: Acao com aval "ver quem esta na rede" (network_scan)

Status: **proposto em 22/10/2026**. Pedido do Voide (22/10): o scan de rede do inventario do
Kali-Bunker entra como acao com aval. E a primeira acao nova depois das ja existentes
(lock_screen, webcam_photo) e segue o mesmo trilho do ADR-016.

## Contexto

O inventario do Kali-Bunker (claude/inventario-kali-bunker.md) lista "scan de rede (nmap -sn)"
como acao a trazer com aval. E uma leitura: descobre quais aparelhos estao ligados na rede local
do proprio computador. Nao muda nada no computador nem na rede.

## Decisao

1. **Acao fechada do catalogo (ADR-016).** `network_scan` entra no catalogo de acoes, como
   `lock_screen` e `webcam_photo`. Toda a protecao do ADR-016 vale: o dono pede, aprova com o PIN
   (ou codigo por e-mail), o backend assina um digest canonico e o agente so executa se o digest
   bater. Nao ha texto livre nem shell.
2. **Opcional e desligada por padrao.** So funciona se o dono ligar na instalacao:
   `AVAL_ACTIONS=...,network_scan`.
3. **O agente escolhe o alvo, nunca o servidor.** O servidor manda apenas o tipo `network_scan`,
   sem parametro. O agente varre somente as **redes IPv4 privadas das suas proprias interfaces**
   (10/8, 172.16/12, 192.168/16), pulando qualquer sub-rede maior que 256 enderecos para a
   varredura ser rapida e limitada. Nunca recebe um alvo de fora.
4. **Programa e argumentos fixos.** O agente roda `nmap -sn -oG - <cidr...>`, sem shell. `-sn` e
   so descoberta de hosts (ping scan): nao faz scan de portas, nao altera nada.
5. **Resultado volta como texto.** O agente devolve uma lista curta e legivel (IP e nome, quando
   houver), assinada com tamanho e SHA-256 como qualquer resultado. O bot entrega como **mensagem**
   no chat do dono (ate ~3500 caracteres; o resto e truncado). O texto e apagado do banco assim que
   e entregue.
6. **Auditoria.** `action.completed` e `action.delivered` registram a acao; a lista de aparelhos
   nunca vai para a auditoria.
7. **Permissao no Linux.** O instalador instala o `nmap` se faltar e adiciona um drop-in
   (`scan.conf`) com `AmbientCapabilities=CAP_NET_RAW`, para o `nmap -sn` poder mandar sondas
   ICMP/ARP. Sem essa capacidade, o nmap ainda funciona por TCP, com menos precisao.

## Consequencias

- O dono ve, na hora e pelo Telegram (e, no proximo passo, pelo painel web), quem esta na rede
  local de cada computador dele.
- Um agente comprometido poderia mandar uma lista falsa, mas so para o dono, com o mesmo nivel de
  confianca que ja existe na telemetria. A acao e read-only: nao abre porta, nao muda firewall.
- macOS: o `nmap -sn` roda tambem no Mac se o `nmap` estiver instalado (`brew install nmap`); sem
  root a descoberta e por TCP.
- Esta acao NAO banir nem bloqueia nada. "Banir IP/MAC" e uma acao separada, com suas proprias
  travas, e fica para um ADR proprio.
