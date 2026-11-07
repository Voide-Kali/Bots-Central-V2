# ADR-036: localizacao de computador por IP (opt-in)

Status: **proposto em 2026-11-07**. Pedido do Voide: ver onde um computador esta (ex.: notebook de
empresa que some), pelo IP, no painel.

## Contexto

A telemetria (ADR-012) foi desenhada de proposito **sem enderecos de rede** ("no processes, files,
users, network addresses, or peripherals"), por privacidade. Reportar o IP e a localizacao de um
computador e rastreamento, e nao pode ser pendurado na telemetria sem furar esse limite. Alem
disso, os agentes falam com o backend pela rede Tailscale, entao o backend **nao enxerga** o IP
publico real do computador na conexao - so o proprio agente sabe.

## Decisao

Um **canal proprio, opt-in**, separado da telemetria:

1. **Opt-in por computador.** O agente so coleta e reporta rede quando o sensor `network_location`
   esta ligado na instalacao (lista `sensors`, como os outros sensores). Sem ele, nada e coletado
   nem enviado. O dono liga so onde faz sentido (ex.: notebooks da empresa).

2. **Canal `net` dentro do heartbeat assinado.** Quando ligado, o agente inclui um claim `net` no
   JWS do heartbeat, com `public_ip` (melhor esforco, via servico de echo) e `local_ips` (interfaces
   nao-loopback). Reaproveita a assinatura EdDSA, a sequencia e o anti-replay do heartbeat - nenhuma
   superficie de autenticacao nova. A telemetria (`tel`) continua sem enderecos.

3. **Backend guarda o ultimo estado no device.** `last_public_ip`, `last_local_ips`,
   `network_reported_at`. Nada de serie temporal: so o estado atual.

4. **Geolocalizacao no servidor (cidade/pais).** O painel tem CSP `connect-src 'self'`, entao o
   navegador nao pode chamar um servico de geo. O **backend** resolve o IP publico em
   cidade/regiao/pais/lat-long, por um geolocalizador **injetavel** (interface), com cache no device
   (`geo_*`, `geo_at`) para nao consultar a cada leitura. O painel mostra cidade/pais e um link
   externo "ver no mapa" (navegacao, permitida pela CSP).

5. **Privacidade.** E rastreamento de localizacao aproximada, por IP (nivel cidade, nao GPS).
   Opt-in, so do dono, auditado quando muda. Deve ser citado na Politica de Privacidade antes de uso
   com terceiros. A IA nao tem acesso a isso como ferramenta.

## Como fica (fatias)

- **Parte 1 (pipeline):** sensor opt-in no agente, claim `net`, ingestao e guarda no backend,
  exibicao do IP cru no painel. Validavel numa maquina real antes de prosseguir.
- **Parte 2 (localizacao):** geolocalizacao no backend + cidade/pais/mapa no painel.

## Limites honestos

- O IP publico vem por melhor esforco (um servico de echo externo); pode faltar atras de certas
  redes. Local_ips sempre saem quando ligado.
- Geolocalizacao por IP e aproximada (cidade/operadora), nao endereco exato. Depende de um servico
  externo de geo, que pode errar ou ficar fora do ar; o painel degrada para so o IP.
- Nao e antifurto: um notebook desligado ou sem rede nao reporta.

## Alternativas descartadas

- **Pendurar o IP na telemetria:** fura o limite de privacidade do ADR-012.
- **Backend ler o IP da conexao:** os agentes vem por Tailscale; o backend nao ve o IP publico real.
- **Geo no navegador:** barrado pela CSP `connect-src 'self'` do painel.
