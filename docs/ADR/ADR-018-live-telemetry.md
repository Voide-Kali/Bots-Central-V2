# ADR-018: Telemetria ao vivo (1 por segundo) enquanto o dono olha

Status: **proposto em 22/10/2026 a pedido do Voide** ("quero que atualize a cada segundo, com
um gráfico de cada computador"). Muda o protocolo do agente, então fica registrado aqui.

## Contexto

O agente manda um heartbeat assinado a cada 30 s (ADR-012), com CPU, memória, disco e
temperatura. O painel, portanto, só pode mudar a cada 30 s. O Voide quer ver os números
mudando a cada segundo e um gráfico com picos e baixas ao abrir um computador.

Mandar 1 heartbeat por segundo o tempo todo multiplicaria por 30 o tráfego, as escritas no
banco e o disco do agente (a sequência anti-replay é gravada a cada envio), mesmo quando
ninguém está olhando.

## Decisão

1. **Modo ao vivo sob demanda.** O painel, enquanto o detalhe de um computador está aberto,
   chama `POST /api/v1/devices/{id}/watch` (dono, autenticado). O servidor grava
   `devices.live_until = agora + 60 s`. Sem novas chamadas, o modo se desliga sozinho.
2. **Rota nova para o agente:** `POST /api/v1/devices/{id}/live` com um JWS assinado pela
   chave do dispositivo, audiência própria (`bots-central:live:v1`), a mesma sequência
   anti-replay do heartbeat e o mesmo formato de telemetria (`tel`). A resposta é
   `{"live": true|false}`. A amostra só é gravada quando o modo está ligado.
3. **O agente pergunta uma vez por ciclo.** Depois de cada heartbeat normal, o agente novo
   manda um `/live`. Se a resposta for `true`, passa a mandar 1 por segundo, por no máximo
   120 s seguidos, e volta ao ciclo normal assim que a resposta for `false`. Agentes antigos
   não chamam a rota e continuam funcionando como antes (as respostas existentes não mudam).
4. **Limites:** a rota `/live` tem limite próprio de 150 por minuto por dispositivo, além do
   limite por rede antes da verificação da assinatura (o mesmo do heartbeat).
5. **Mac:** a CPU vem de um `/usr/bin/top -l 0 -s 1 -n 0` que fica rodando com o agente
   (programa fixo, argumentos fixos, sem shell). Assim cada amostra é instantânea.
6. **Alertas de recurso:** passam a exigir que o limite seja ultrapassado em amostras que
   cobrem pelo menos 90 s, para que amostras de 1 s não disparem alerta.

## Consequências

- O gráfico mostra o último minuto com resolução de 1 s enquanto o detalhe está aberto, e a
  última hora com as amostras de 30 s.
- Assistir por uma hora grava cerca de 3600 amostras daquele computador. A retenção de 7 dias
  continua valendo.
- Um servidor comprometido não ganha nada novo: o modo ao vivo só aumenta a frequência de dados
  que o agente já manda. O agente continua sem aceitar nenhuma ordem por essa rota.
