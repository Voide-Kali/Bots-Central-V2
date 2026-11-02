# Backup container (ADR-033): Postgres client tools + age, para cifrar cada dump.
# age vem do repositorio community do Alpine (resolvido no build, num host com acesso ao registry).
FROM postgres:17-alpine
RUN apk add --no-cache age
