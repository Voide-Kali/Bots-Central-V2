# ADR-022: Nivel de bateria na telemetria e alerta de bateria fraca

Status: **proposto em 22/10/2026**. Pedido do Voide: acompanhar a bateria dos notebooks junto
com CPU/RAM/disco/temperatura, e avisar quando estiver acabando. E leitura pura, no mesmo trilho
da telemetria assinada (ADR-012) e dos alertas de recurso (ADR-018).

## Contexto

A telemetria do heartbeat (ADR-012) ja carrega metricas agregadas: CPU, carga, memoria, disco,
temperatura e uptime. Falta a bateria, util em notebooks. Como todo o resto da telemetria, e uma
leitura agregada: nao expoe processos, arquivos, usuarios nem rede, e nunca vira acao sobre o
computador.

## Decisao

1. **Dois campos novos, opcionais.** O agente passa a enviar `battery_pct` (inteiro 0-100) e
   `battery_charging` (bool) na claim `tel`, assinada pela chave do dispositivo como o resto. Sem
   bateria, os dois campos saem nulos (desktop, VM).
2. **Coleta best-effort, sem binarios novos de terceiros.**
   - Linux: le `/sys/class/power_supply/BAT*/capacity` e `.../status`.
   - macOS: `/usr/bin/pmset -g batt` (binario fixo do sistema, sem shell), ja no mesmo molde do
     `vm_stat`/`top`.
   - Outras plataformas: nao coleta.
   Uma leitura que falha e omitida, nunca adivinhada. O `Sanitize` do agente derruba valor fora
   de 0-100 (e descarta o flag de carga sem nivel).
3. **Validacao estrita no backend.** `parse_claim` valida `battery_pct` na faixa 0-100 e
   `battery_charging` como booleano, com o mesmo rigor dos outros campos: chave desconhecida,
   tipo errado ou valor fora da faixa rejeitam o heartbeat inteiro. As colunas
   `battery_percent`/`battery_charging` entram em `device_telemetry_samples` (migration 0019),
   com check de faixa.
4. **Alerta de bateria fraca, so leitura.** Quando a amostra mais recente de um dispositivo esta
   em 25% ou menos **e nao esta carregando**, o dono recebe no Telegram
   `Bateria do <computador> em X%`. O aviso e disparado por borda, como o de presenca: so dispara
   ao **entrar** no estado "fraca e descarregando" e fica quieto ate o dispositivo se recuperar
   (carregar ou subir acima do limite) e cair de novo. O estado "ja avisei" vive no processo do
   bot, como os cooldowns do ADR-018: um restart pode repetir um aviso, nunca esconder um.
5. **Bateria e leitura, nunca acao.** Nenhum poder novo sobre o computador. O principio do
   projeto continua: a IA nunca age; acoes so com aval (ADR-016).

## Consequencias

- O painel e o Telegram passam a mostrar a bateria junto das outras metricas.
- O dono e avisado uma vez por episodio de bateria fraca, sem spam.
- Nenhuma mudanca de seguranca: mesma claim assinada, mesma validacao, nenhuma acao nova.
