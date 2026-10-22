# Regras de trabalho (pessoas e IAs)

Leia antes: `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`.

## Git

- Nunca altere a `main` direto. **Uma branch por tarefa, sempre a partir da `main` atual.**
  Evite PRs empilhados; se precisar, mescle o de baixo antes de abrir o de cima.
- Merge só com CI verde no SHA exato e aprovação do responsável.
- Nunca: `push --force` na `main`, apagar branches, mudar visibilidade do repo ou mesclar sem
  confirmação explícita.
- Nenhuma IA aprova o próprio trabalho: peça revisão a outra pessoa/sessão.
- Não commite binários, `.env`, chaves, tokens ou dumps.

## Mudanças

- Só o escopo pedido. Mudança de arquitetura ou de segurança (auth, identidade, autorização,
  revogação, protocolo, auditoria) exige ADR em `docs/ADR/` ou aprovação explícita.
- Descreva a mudança no PR. Atualize `docs/CURRENT_STATE.md` **só** se o estado do sistema
  mudou (nova capacidade, restrição ou risco) — não adicione diário.

## Testes antes do PR

```bash
cd backend && ruff check . && mypy app tests && pytest        # PostgreSQL: scripts/test-db.sh
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
cd agent && go test -race ./... && go vet ./...
```
