# ADR-009: React, TypeScript e Vite para o cliente web

## Contexto

O MVP1 precisa de um cliente web estático, responsivo e independente para os fluxos de
registro, verificação, login e consulta de dispositivos. Não há requisito de renderização
no servidor nem contrato final para login e dispositivos.

## Decisão

Criar o cliente em `frontend/` com React, TypeScript estrito e Vite. A interface usa uma
camada de API same-origin isolada das páginas e adaptadores HTTP/mock explicitamente
configurados. Não será introduzido framework SSR nesta etapa.

## Consequências

React fornece composição de telas e estados acessíveis; TypeScript limita suposições sobre
contratos ainda pendentes; Vite mantém o ciclo de build e testes pequeno. O adaptador mock
existe apenas para desenvolvimento/teste e não representa autorização. Esta decisão é
exclusiva do cliente web e não altera a ADR-004: Flutter/Dart continua reservado para o
cliente mobile futuro.
