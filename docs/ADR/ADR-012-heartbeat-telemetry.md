# ADR-012: Telemetria de sistema dentro do heartbeat assinado

Status: proposto (2026-10-21).

## Contexto

A demo precisa mostrar CPU, memória, disco, temperatura e tempo ligado de cada dispositivo.
O heartbeat Device Online V0.1 já é um JWS EdDSA assinado pela chave do dispositivo, com
sequência anti-replay. Um canal novo exigiria outra autenticação e outro limite de taxa.

## Decisão

1. O heartbeat ganha um claim **opcional** `tel` dentro do mesmo JWS (`aud`
   `bots-central:heartbeat:v1` inalterado). Agentes antigos, sem `tel`, continuam válidos.
2. Formato v1 (todas as chaves opcionais exceto `v`):
   `{"v":1,"cpu_pct":0–100,"load1":≥0,"cpus":1–65536,"mem_total","mem_used","disk_total","disk_used":bytes,"temp_c":-50–150,"uptime_s":segundos}`.
   Pares total/usado vêm juntos e `usado ≤ total`.
3. Validação **estrita** no backend: chave desconhecida, tipo errado ou valor fora da faixa
   rejeita o heartbeat inteiro como prova inválida, sem nenhuma mutação. O agente sanitiza antes
   de enviar, descartando leituras estranhas, para nunca perder presença por causa de um sensor.
4. A amostra é gravada na mesma transação em que o heartbeat é aceito; heartbeat repetido ou
   antigo (409) não grava nada. Retenção de 7 dias por dispositivo, podada no insert.
5. O agente só envia `tel` depois que o dispositivo está `active` (aprovado pelo dono).
6. Coleta somente de contadores agregados do sistema: nada de processos, arquivos, usuários,
   endereços de rede, câmera ou periféricos. No macOS a única execução externa é o binário fixo
   `/usr/bin/vm_stat`, sem shell e sem argumentos; temperatura e CPU% instantânea não são
   coletadas no macOS (sem cgo), e `load1` é enviado no lugar.
7. API: `GET /api/v1/devices` inclui `telemetry` (última amostra ou `null`);
   `GET /api/v1/devices/{id}/telemetry?minutes=1..1440` devolve o histórico, só para o dono
   (outro dono recebe 404).

## Consequências

- Telemetria herda autenticidade, integridade e anti-replay do heartbeat sem credencial nova.
- Um bug de telemetria no agente pode derrubar presença; mitigado pela sanitização no agente.
- ~2.880 linhas/dia por dispositivo com heartbeat de 30 s; aceitável no PostgreSQL com índice
  `(device_id, recorded_at DESC)` e retenção de 7 dias.
