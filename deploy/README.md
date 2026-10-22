# Deploy — servidor de casa (Ubuntu Server + Tailscale)

Stack em [`server/`](server/): PostgreSQL 17, migration, backend (FastAPI), bot do Telegram,
painel web servido pelo Caddy e backup diário. **Nenhuma porta fica aberta na internet:** o
Caddy escuta só no IP do Tailscale e pega o certificado `*.ts.net` do `tailscaled` local.

```
iPhone / Mac / Kali ──(Tailscale)──► Caddy :443 ──► backend :8000 ──► PostgreSQL
                                        └─ painel (arquivos estáticos)
Telegram ◄──(long polling, saída)── bot      backup ──► HD 1 TB
```

## 0. Pré-requisitos (uma vez)

No painel do Tailscale (login.tailscale.com → **DNS**): ative **MagicDNS** e **HTTPS Certificates**.

No servidor:

```bash
# Docker oficial
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # depois saia e entre de novo no SSH
```

O HD de 1 TB já está montado em `/mnt/storage`. Crie a pasta de backup:

```bash
sudo mkdir -p /mnt/storage/bots-central-backups && sudo chmod 700 /mnt/storage/bots-central-backups
```

## 1. Código e segredos

```bash
git clone https://github.com/Voide-Kali/Bots-Central-V2.git ~/bots-central
cd ~/bots-central
git checkout deploy/home-server   # enquanto o PR do deploy não estiver na main
cd deploy/server
./generate-env.sh          # cria .env com senhas e chaves aleatórias
tailscale status --self    # nome completo: algo.tailXXXX.ts.net
tailscale ip -4            # IP 100.x.y.z
nano .env                  # preencha os REPLACE_ME
```

- `SMTP_*`: o Gmail do sistema, com verificação em 2 etapas e uma **senha de app**.
- `TELEGRAM_*`: token e usuário do bot criado no @BotFather.
- O `.env` fica só no servidor (`chmod 600`). Nunca no Git, nunca em chat de IA.

## 2. Subir

```bash
docker compose --env-file .env up -d --build
docker compose ps
docker compose logs -f backend telegram web   # Ctrl+C para sair
```

Baixe o modelo da IA local (uma vez, ~2 GB):

```bash
docker compose exec ollama ollama pull qwen2.5:3b
```

Teste do celular (com Tailscale ligado): `https://SEU_SERVIDOR.tailXXXX.ts.net` → painel.
Saúde: `https://SEU_SERVIDOR.tailXXXX.ts.net/api/v1/health`.

## 3. Agentes (Mac e Kali)

Nos dois aparelhos, com Tailscale ligado, compile e configure o agente apontando para
`https://SEU_SERVIDOR.tailXXXX.ts.net` (veja `agent/README.md`). O certificado é público
(Let's Encrypt), então o agente confia nele sem configuração extra.

## Diagnóstico

Algo não funciona? Rode `./doctor.sh` nesta pasta. Ele confere `.env` (sem mostrar segredos), containers, login no Gmail, token do Telegram, modelo da IA e o painel, e diz como corrigir cada problema.

## Operação

| Tarefa | Comando |
|---|---|
| Atualizar para a `main` | `git pull && docker compose --env-file .env up -d --build` |
| Ver backups | `ls -lh /mnt/storage/bots-central-backups` |
| Restaurar backup | `docker compose exec -T db pg_restore -U bots_central -d bots_central --clean < ARQUIVO.dump` |
| Parar tudo | `docker compose down` (os dados ficam no volume) |

## Riscos conhecidos

- Backup fica na mesma máquina (outro disco): não protege de roubo/incêndio.
- Se o Tailscale demorar a subir após reiniciar, o Caddy reinicia sozinho até o IP existir.
- Plano gratuito do Tailscale é para uso não comercial (ver `docs/ROADMAP.md`).
