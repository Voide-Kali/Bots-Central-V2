# Bots Central V2 (Aval)

Plataforma de gestao de dispositivos. Um backend FastAPI com PostgreSQL, um agente em Go por
computador, o painel web (React) e o bot do Telegram. A IA conversa e explica, mas **nenhuma acao
num computador acontece sem o aval do dono** (PIN de 6 digitos). Nada fica exposto na internet alem
da pagina publica de download (`/baixar`); o acesso ao painel e a API e pela rede privada Tailscale.

## Desenvolvimento local

1. Copie `.env.example` para `.env` e troque a senha de desenvolvimento.
2. Rode `docker compose up --build` (sobe backend, bot, migracoes e PostgreSQL).
3. Abra `http://localhost:8000/api/v1/health`.

Para o backend em Python, rode a partir de `backend/`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Deploy no servidor

Veja `deploy/README.md` (clona em `~/aval`, sobe a stack com Docker + Tailscale, gera os
instaladores e a landing). O papel de banco de menor privilegio e os backups cifrados estao em
`docs/ADR/ADR-032-db-least-privilege.md` e `docs/ADR/ADR-033-encrypted-backups.md`.

## Documentacao

- `docs/CURRENT_STATE.md` — o que esta pronto hoje (fonte autoritativa do estado).
- `docs/ARCHITECTURE.md` e `docs/SECURITY_MODEL.md` — desenho e modelo de seguranca.
- `docs/ROADMAP.md` — plano de entrega.
- `AGENTS.md` — regras de trabalho (humanos e IAs) para o repositorio.
