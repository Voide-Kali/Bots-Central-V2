# ADR-039: visibilidade e controle de sensores pelo painel, e ciclo de vida dos dados

Status: **rascunho proposto em 2026-11-09, aguardando aprovacao do Voide**. Nasce dos objetivos
de privacidade da preparacao para a feira (ver os sensores ativos, poder desliga-los, e apagar os
dados correspondentes ao desligar) e do achado "desligar o sensor nao apaga o ultimo IP" das
revisoes de seguranca.

## Contexto

Hoje os sensores (`failed_login_photo`, `network_location`) sao escolhidos no **install** do
agente (`AVAL_SENSORS=...`, gravado no `config.json` local). Consequencias:

- O dono **nao ve pelo painel** quais sensores estao ativos em cada computador.
- O dono **nao consegue desligar** um sensor pelo painel; precisa mexer no computador.
- Quando um sensor para (desligado no install ou agente reinstalado sem ele), o backend
  **mantem o ultimo dado** (ex.: `last_public_ip`/`last_local_ips`/`network_reported_at`), porque
  so atualiza quando o heartbeat traz o claim; sem o claim, o valor antigo permanece. O painel ja
  passou a marcar isso como "pode estar desatualizado" (PR da transparencia), mas o dado antigo
  continua guardado.

## Por que isso exige ADR

Ligar/desligar um sensor **a distancia** significa o servidor mandar uma ordem que **muda o
comportamento do agente**. Isso e um **canal de controle novo** (protocolo) com **autorizacao**
(quem pode, como o agente verifica a ordem, anti-replay) e **auditoria**. Mexe exatamente nas
areas que o AGENTS.md protege. Por isso aqui vai so a proposta; **nada implementado**.

## Decisao proposta (em fatias, da mais segura para a mais invasiva)

1. **Visibilidade (fatia 1, sem canal novo).** O painel mostra, por computador, quais sensores
   estao reportando (derivado do que chega: se vem o claim `net`, o sensor de rede esta ativo; se
   chegam eventos de `failed_login`, aquele sensor esta ativo). So leitura, sem ordem ao agente.

2. **Ciclo de vida do dado ao parar de reportar (fatia 2, backend).** Quando o agente **deixa de
   mandar** o claim de um sensor por N heartbeats (ex.: alguns minutos), o backend **apaga** o dado
   correspondente (ex.: zera `last_public_ip`/`last_local_ips`/`network_reported_at`) e **registra**
   um evento de auditoria (`device.network_cleared`). Nao e um canal novo — e uma regra de
   retencao sobre o heartbeat que ja existe. Precisa de decisao porque mexe em **dados e
   auditoria**.

3. **Desligar o sensor pelo painel (fatia 3, canal de controle - a parte pesada).** O backend
   passa a mandar ao agente uma ordem assinada de "desligar o sensor X", que o agente **verifica
   como verifica uma acao** (digest canonico proprio, audiencia propria, anti-replay pela mesma
   sequencia), aplica e confirma. Opt-in continua valendo: so desliga o que ja estava ligado.
   Esta fatia e a que mais precisa de desenho cuidadoso (fail-closed, autorizacao, auditoria).

## Decisoes que preciso de voce

- **(a) Ate onde ir para a feira.** Recomendacao: **fatias 1 e 2** (ver os sensores e apagar o
  dado quando para de chegar) ja entregam o essencial de privacidade sem canal de controle novo. A
  **fatia 3** (desligar remoto) pode ficar para depois da feira.
- **(b) Janela da fatia 2.** Quantos heartbeats/minutos sem o claim antes de apagar o dado? (ex.:
  5 minutos.)
- **(c) Fatia 3, se for em frente.** A ordem de desligar reusa o digest de acao (`aval-action-v1`)
  com uma audiencia nova, ou um protocolo proprio? Isso define o ADR de implementacao.

## Consequencias

- Fatias 1 e 2 melhoram a privacidade sem criar canal de controle; o custo e um pouco de backend
  (deteccao de "parou de reportar") e painel (mostrar sensores ativos).
- Fatia 3 adiciona poder real (o servidor muda o agente): so com desenho de autorizacao/anti-replay
  e auditoria, em ADR proprio de implementacao.

## Nao implementado neste rascunho

Apenas o desenho. A implementacao vem em PR proprio **depois do seu aval** e da escolha das fatias,
com testes (fatia 2: apaga o dado e audita quando o claim some; fatia 3: recusa ordem sem
assinatura/replay, so desliga o que estava ligado).
