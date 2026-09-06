# ADR-002: PostgreSQL como banco principal

## Contexto

A plataforma requer persistência relacional confiável para futuros dados e auditoria.

## Decisão

Usar PostgreSQL como banco principal, acessado pelo backend via SQLAlchemy.

## Consequências

Migrations são controladas por Alembic e clientes futuros não acessam o banco direto.
