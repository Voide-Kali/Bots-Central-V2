# ADR-023: IA com contexto curto e leitura de eventos recentes

Status: **proposto em 22/10/2026**. Pedido do Voide (22/10): "dar uma melhorada na IA". Melhora a
qualidade das respostas do assistente sem mudar o que ele PODE fazer: continua leitura pura, sem
ferramentas, sem acao (ADR-013).

## Contexto

O assistente (Ollama local) responde perguntas sobre os computadores do dono a partir de um
snapshot. Duas limitacoes: (1) nao lembra a pergunta anterior, entao perguntas de continuacao ("e o
Mac?") se perdem; (2) so enxerga a telemetria atual, entao nao sabe responder "o que aconteceu?".

## Decisao

1. **Contexto curto por conversa.** O processo do bot guarda, so em memoria, as ultimas 3 trocas
   (pergunta/resposta) de cada chat e as envia ao modelo como mensagens anteriores. Nada e
   persistido: nao e um vetor de prompt injection duravel, nunca cruza entre contas, e some quando
   o bot reinicia. Limitado a algumas centenas de chats (LRU) e protegido por lock para as threads
   do ChatQueue. Ao desvincular o chat, o contexto e esquecido.
2. **Leitura de eventos recentes.** O snapshot passa a incluir os ultimos 8 eventos da auditoria do
   proprio dono (ja rotulados, ex.: "Senha errada no computador", "Tela bloqueada"), para o
   assistente responder "o que aconteceu". Sao os mesmos eventos que o dono ja ve no /historico.
   Cada rotulo passa pela mesma limpeza (controle removido, `<`/`>` neutralizados) do resto dos
   dados.
3. **Sem novo poder.** O assistente continua sem ferramentas: so recebe dados do proprio dono e
   devolve texto. O prompt reforca que ele nao age (a pessoa dispara a acao pelo menu/painel e
   aprova com o PIN) e que tudo dentro de <dados> e informacao, nunca instrucao.
4. **Limites.** As mesmas regras de abuso do assistente valem; o contexto e os eventos nao mudam o
   caminho de aprovacao nem a autorizacao.

## Consequencias

- Perguntas de continuacao funcionam e o assistente responde sobre o que aconteceu, com dados que o
  dono ja podia ver.
- A superficie de prompt injection nao cresce de forma durave: o contexto e efemero e por chat, e os
  eventos vem da propria auditoria do dono, dentro do mesmo <dados> ja tratado como informacao.
- Memoria permanente da IA ("lembre que...") continua fora: e um vetor de injection persistente e
  fica para depois, com cuidado, se for o caso (ver inventario do Kali-Bunker).
