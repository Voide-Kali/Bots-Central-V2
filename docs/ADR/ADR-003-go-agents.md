# ADR-003: Go para agents

Status da decisão: aceita.

Status de implementação: o Linux Agent MVP-1 implementa identidade Ed25519, enrollment e heartbeat para o contrato Device Online V0.1. Outros agents e poderes remotos não estão implementados.

## Contexto

Agents precisam de distribuição e execução eficientes em dispositivos.

## Decisão

Usar Go para agents.

## Consequências

O MVP-1 valida a escolha com um Agent Linux restrito. Windows, atualização assinada completa e ações remotas exigem decisões posteriores.
