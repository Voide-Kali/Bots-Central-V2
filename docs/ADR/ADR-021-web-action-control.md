# ADR-021: Controle de acoes pelo painel web

Status: **proposto em 22/10/2026**. Pedido do Voide (22/10): "todas as funcoes que dao para ser
gerenciadas pelo Telegram, eu quero que tambem possam ser gerenciadas pelo site do navegador" -
para o caso de o dono estar com o celular longe e controlar pelo proprio computador.

## Contexto

Hoje as acoes do ADR-016 (bloquear tela, foto, scan de rede) so podem ser disparadas pelo
Telegram. O painel web so cria/mostra o PIN e aprova pareamento. O dono quer paridade: disparar e
aprovar acoes, e ver o resultado, tambem pelo site.

O nucleo ja e agnostico de canal: `request_action` cria o comando pendente, `approve_with_pin`
aprova com o PIN, o agente executa e devolve o resultado assinado. O Telegram e so um adaptador.
Este ADR adiciona um segundo adaptador - o painel web - sobre exatamente o mesmo nucleo. Nenhuma
regra de seguranca nova: a aprovacao continua sendo o mesmo PIN, com o mesmo bloqueio por
tentativas.

## Decisao

1. **Mesmo nucleo, mesmo PIN.** O web reaproveita `request_action(by_pin=True)` e
   `approve_with_pin`. Nao ha caminho de aprovacao novo. O PIN e verificado por
   `action_pin.check_pin` (mesmo bloqueio apos tentativas erradas).
2. **Endpoints autenticados por sessao** (cookie/token do painel, como o resto do `/me` e
   `/devices`), com checagem de origem (CSRF) como os outros POST do painel:
   - `POST /devices/{id}/actions` com `{ "kind": "...", "pin": "######" }`: cria o comando (so do
     proprio dono, so em device ativo dele) e aprova na mesma chamada. Como o dono esta na tela com
     o PIN, pedir e aprovar num passo so e o fluxo natural. Responde `{ "command_id": "..." }` ou
     erro de PIN (errado/bloqueado), device nao encontrado, etc.
   - `GET /devices/{id}/actions/{command_id}`: estado do comando e, quando pronto, o resultado -
     texto (scan) ou aviso de conclusao (bloquear). A foto vem por um endpoint proprio.
   - `GET /devices/{id}/actions/{command_id}/photo`: os bytes da foto (returns_file), uma vez.
3. **Comando do web nao vai para o Telegram.** Um comando criado pelo web tem `chat_id = NULL`,
   entao a entrega do bot o ignora. O web le o resultado pelos endpoints acima. Ao ler um resultado
   pronto, o backend marca como entregue e apaga o payload (foto/scan saem do banco), igual a
   entrega do Telegram.
4. **Uma acao com PIN por vez.** Mantem-se a regra do ADR-016: `request_action(by_pin=True)`
   expira qualquer outro pedido com PIN aberto, do Telegram ou do web. O PIN nunca aprova algo
   diferente do ultimo pedido.
5. **Limites.** Os mesmos limites de abuso ja aplicados as acoes valem aqui (o POST passa pelo
   mesmo AbuseController das rotas do painel).
6. **Paridade, nao poder novo.** O web nao ganha nenhuma acao que o Telegram nao tenha, nem pula o
   PIN. E so um segundo jeito de pedir a mesma coisa.

## Consequencias

- Com o celular longe, o dono controla tudo pelo computador: dispara a acao, digita o PIN ali e ve
  o resultado na hora.
- A superficie de autorizacao cresce (novos endpoints que disparam acao), mas sobre o mesmo nucleo
  e o mesmo PIN; nao ha novo fator de confianca. Esta decisao e registrada aqui por mexer em
  autorizacao (regra do AGENTS.md).
- Daqui pra frente, toda acao nova do ADR-016 nasce nos dois canais (Telegram e web) sem trabalho
  extra de seguranca: os dois adaptadores chamam o mesmo nucleo.
