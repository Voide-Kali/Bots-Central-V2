# Estado atual — Aval (repositorio Bots-Central-V2)

Retrato do sistema na `main`. Atualize **so quando o estado mudar de verdade** (nova
capacidade, nova restricao, novo risco). O detalhe de cada mudanca fica no PR e no git;
o diario antigo esta em [HISTORY.md](HISTORY.md).

Ultima revisao: 2026-11-13.

## O que funciona

| Area | Situacao | Referencia |
|---|---|---|
| Conta | Cadastro, verificacao de e-mail (codigo), login, sessoes no servidor, refresh com rotacao e deteccao de replay, logout automatico apos 1 h de inatividade, logout | [AUTH.md](AUTH.md), ADR-006/007/008, ADR-025 |
| Recuperacao de senha | Codigo de 8 digitos por e-mail; troca derruba sessoes, Telegram e comandos abertos | ADR-014 |
| Papeis | `user` e `admin` na tabela `users`; promocao so por comando no servidor (`python -m app.admin promote`), nunca pela web | ADR-017 |
| Dispositivos | Pareamento por token de uso unico, identidade Ed25519, aprovacao humana pelo fingerprint, heartbeat JWS EdDSA com anti-replay, online/offline; renomear o nome de exibicao (`POST /devices/{id}/name`) e remover (`DELETE /devices/{id}`, apaga o computador e a telemetria; auditoria preservada), ambos so do dono e auditados. Localizacao de rede opt-in (ADR-036): com o sensor `network_location` ligado, o agente reporta IP publico e IPs locais no claim `net` do heartbeat; o painel mostra o IP | [DEVICE_ONLINE_V01.md](DEVICE_ONLINE_V01.md) |
| Telemetria | CPU/carga, memoria, disco, temperatura (Linux), uptime dentro do heartbeat assinado; 7 dias de historico | ADR-012 |
| Telemetria ao vivo | Sob demanda enquanto o detalhe de um computador esta aberto: `POST /devices/{id}/watch` (dono) liga o modo por 60 s; o agente manda 1 amostra/s (`POST /devices/{id}/live`, JWS `aud bots-central:live:v1`, mesma sequencia anti-replay) por ate 120 s; grafico no painel | ADR-018 |
| Telegram | Vinculo por codigo, menu de botoes inline, `/painel`, `/computadores`, `/historico`, `/ia`, alertas online/offline, resumo diario, alertas de recursos (CPU, disco, temperatura, bateria); acoes por botao e por frases de padrao fixo (`app/telegram/intents.py`, nao e o modelo de IA) | [TELEGRAM.md](TELEGRAM.md), ADR-011, ADR-016 |
| IA local | Ollama, **somente leitura**, sem ferramentas, so os dados do proprio usuario; sem caminho para iniciar ou aprovar acoes | ADR-013 |
| Aprovacao de acoes | **PIN de 6 digitos** criado no painel (exige a senha da conta), guardado como HMAC com subchave HKDF dedicada (`aval/action-pin/v1`); PINs obvios recusados; 5 erros travam por 15 min. O **codigo de 8 digitos por e-mail** continua como alternativa quando nao ha PIN configurado | ADR-016 (adendo), ADR-038, `app/auth/action_pin.py` |
| Separacao de chaves HMAC | HKDF (SHA-256) com domainios separados por finalidade: `aval/rate-limit/v1`, `aval/reset-code/v1`, `aval/approval-code/v1`, `aval/action-pin/v1`. Flag-day executado (migracao 0024); PINs antigos invalidados | ADR-038 |
| Acoes com aval | Catalogo fechado: `send_file`, `lock_screen`, `unlock_screen`, `webcam_photo`, `network_scan`, `power`. Cada agente opta explicitamente em cada acao (`allowed_actions` no `config.json`; vazio = nenhuma). O backend assina um digest canonico (`aval-action-v1`) e o agente so executa se o digest bater, sem shell | ADR-015, ADR-016, ADR-020, `app/devices/commands.py` (`ACTIONS`) |
| Acoes pelo painel web | Paridade com o Telegram para `lock_screen`, `unlock_screen`, `webcam_photo`, `network_scan`, `power` (desligar/reiniciar/suspender, com confirmacao): `POST /devices/{id}/actions` pede e aprova com o PIN na mesma chamada; `GET` le estado/resultado; foto por endpoint proprio. Mesmo nucleo e mesmo PIN, sem poder novo; comando do web tem `chat_id = NULL` e nao vai ao Telegram | ADR-021, `app/api/v1/routes/device_actions.py` |
| Sensor de senha errada | Opcional e **desligado por padrao** (`AVAL_SENSORS=failed_login_photo`), **so Linux**: o agente le `journalctl -f -o json`, e numa falha de autenticacao tira uma foto e envia por `POST /devices/{id}/events` (JWS `aud bots-central:event:v1`). O texto do diario nunca sai do PC; so vai o nome do programa. Limite de 1 foto/min no agente e 5/10 min no servidor; foto entregue ao Telegram do dono e apagada | ADR-019, `agent/internal/sensors/failedlogin.go` |
| Painel de administracao | Aba **Admin** so quando `/auth/me` responde `role: admin`; rotas `/api/v1/admin/*` com o mesmo erro de rota inexistente. Mostra saude, contagens, lista de usuarios, falhas recentes e historico de todos; **ativa conta pendente** (`admin.user_activated`). Nao ve arquivos/fotos, PINs/senhas nem executa acoes | ADR-017, `app/admin/`, `app/api/v1/routes/admin.py` |
| Auditoria | Append-only (trigger no PostgreSQL), mesma transacao da acao, sem segredos (nem PIN, nem rotulo, nem conteudo) | `app/audit` |
| Agente | Linux e macOS (Intel e Apple Silicon); executor das acoes do catalogo; instaladores com servico | [agent/README.md](../agent/README.md) |
| Painel web | React: login, cadastro, recuperacao, dispositivos, telemetria, grafico ao vivo, vinculo do Telegram, PIN, acoes, aba Admin | ADR-009, ADR-018, ADR-021 |
| Servidor | Compose so no Tailscale, HTTPS `*.ts.net`, backup diario | [deploy/README.md](../deploy/README.md) |

## Acoes do catalogo (estado real)

| Acao | Executa no agente | Resultado | Web? |
|---|---|---|---|
| `send_file` | le so a pasta compartilhada (`shared_dir`), sem symlink/hard link, ate 10 MB | arquivo | nao (precisa de nome de arquivo; fluxo proprio) |
| `lock_screen` | `loginctl lock-sessions` (Linux) / `pmset displaysleepnow` (Mac) | so status | sim |
| `unlock_screen` | `loginctl unlock-sessions` (Linux) | so status | sim |
| `webcam_photo` | `fswebcam` (Linux) / `imagesnap` (Mac), ate 2 MB | foto | sim |
| `network_scan` | `nmap -sn` so nas redes IPv4 privadas das proprias interfaces, sub-redes <= 256 enderecos | texto | sim |
| `power` | `systemctl poweroff\|reboot\|suspend` (Linux) / `shutdown`/`pmset sleepnow` (Mac); modo em `file_name`, responde "ok" e age apos uma folga curta. Linux: regra polkit libera so o usuario `aval-agent` | so status | sim (com confirmacao no painel) |

Acoes listadas no catalogo do ADR-016 mas **ainda nao implementadas**: `ban`, `apt_check`,
`apt_upgrade`, `vault_reveal`/`vault_delete`.

## Telegram — comandos e frases

Comandos: `/status`, `/computadores`, `/scan`, `/rede`, `/bloquear`, `/desbloquear`, `/foto`,
`/energia`, `/historico`, `/painel`, `/ia`, `/ajuda`.

Frases reconhecidas por padrao fixo (regex, nao IA): "bloqueia o PC", "desbloqueia o PC",
"tira foto do PC", "escaneia a rede", "desliga o PC", "reinicia o PC", "suspende o PC".

Alertas automaticos: online/offline, resumo diario, alertas de CPU, disco, temperatura e bateria.

## Validacao

- CI em todo push/PR: backend (ruff, mypy, pytest com PostgreSQL 16, pip-audit), frontend
  (testes, lint, typecheck, build), agente (`go test -race`, `go vet`), gitleaks.
- 460+ testes nos 3 componentes (backend ~306, frontend ~116, agente ~40+).
- Cobertura do backend: ~30% (areas com menor cobertura: telegram/).

## Ainda nao validado em producao

- Servidor de casa no ar, Telegram e Gmail reais, Ollama real, instaladores no Mac e no Kali,
  camera e `nmap` reais, `journalctl`/grupo `systemd-journal` para o sensor.

## Fora do escopo atual

App Flutter, acesso remoto (RustDesk), IA de e-mail, instalacao de programas, agente Windows,
organizacoes com varios membros, sensor de senha errada no macOS. Ver [ROADMAP.md](ROADMAP.md).

## Riscos conhecidos (aceitos nesta fase)

- O e-mail e a raiz de confianca: recupera a senha, cria a conta e (sem PIN) aprova acoes. A
  conta de e-mail precisa de 2FA.
- O PIN e digitado no mesmo celular do Telegram: protege contra celular desbloqueado/roubado,
  nao contra quem tambem sabe o PIN.
- A aprovacao e verificada no servidor; um servidor comprometido poderia aprovar sozinho.
  Mitigacao futura: aprovacao assinada no celular e verificada pelo agente.
- Uma conta de administrador roubada ve a lista de e-mails dos usuarios (nao ve conteudo, PINs
  nem senhas). Mitigacao: PIN e senha longos, sessao curta, acesso so pela rede Tailscale.
- Um agente comprometido pode mandar telemetria, scan ou fotos falsas, mas so para o dono, com
  os limites de taxa descritos.
- Servidor e backup na mesma casa; Tailscale gratuito e para uso nao comercial.
- Detalhes em [THREAT_MODEL.md](THREAT_MODEL.md) e nos ADRs.
