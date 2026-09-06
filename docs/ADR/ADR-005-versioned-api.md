# ADR-005: API versionada desde o início

## Contexto

Clientes futuros precisarão de contratos HTTP evolutivos e compatíveis.

## Decisão

Publicar rotas da API sob o prefixo `/api/v1` desde a foundation.

## Consequências

Novas rotas seguem a versão atual ou introduzem uma nova versão de forma explícita.
