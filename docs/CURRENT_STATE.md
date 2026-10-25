# Estado atual — Aval (repositório Bots-Central-V2)

Retrato do sistema nesta branch (`feat/web-actions`, ainda não mesclada na `main`). Atualize
**só quando o estado mudar de verdade** (nova capacidade, nova restrição, novo risco). O detalhe
de cada mudança fica no PR e no git; o diário antigo está em [HISTORY.md](HISTORY.md).

Última revisão: 2026-10-22.

> **Atenção (fonte da verdade):** este documento descreve o código desta branch, que reúne
> ADR-016 a ADR-021 ainda não mescladas na `main`. Para o que já está na `main`, veja
> [DISCREPANCIES-2026-10.md](DISCREPANCIES-2026-10.md). Rótulos de "disponível" na feira/site
> devem seguir o estado da `main`, não o desta branch, até o merge.

## O que funciona

| Área | Situação | Referência |
|---|---|---|
| Conta | Cadastro, verificação de e-mail (código), login, sessões no servidor, refresh com rotação e detecção de replay, logout automático após 1 h de inatividade, logout | [AUTH.md](AUTH.md), ADR-006/007/008, ADR-025 |
| Recuperação de senha | Código de 8 dígitos por e-mail; troca derruba sessões, Telegram e comandos abertos | ADR-014 |
| Papéis | `user` e `admin` na tabela `users`; promoção só por comando no servidor (`python -m app.admin promote`), nunca pela web | ADR-017 |
| Dispositivos | Pareamento por token de uso único, identidade Ed25519, aprovação humana pelo fingerprint, heartbeat JWS EdDSA com anti-replay, online/offline | [DEVICE_ONLINE_V01.md](DEVICE_ONLINE_V01.md) |
| Telemetria | CPU/carga, memória, disco, temperatura (Linux), uptime dentro do heartbeat assinado; 7 dias de histórico | ADR-012 |
| Telemetria ao vivo | Sob demanda enquanto o detalhe de um computador está aberto: `POST /devices/{id}/watch` (dono) liga o modo por 60 s; o agente manda 1 amostra/s (`POST /devices/{id}/live`, JWS `aud bots-central:live:v1`, mesma sequência anti-replay) por até 120 s; gráfico no painel | ADR-018 |
| Telegram | Vínculo por código, menu de botões inline (estilo Kali-Bunker, sem teclado fixo antigo), `/painel`, `/computadores`, `/historico`, `/ia`, alertas online/offline; ações por botão e por frases de padrão fixo (`app/telegram/intents.py`, não é o modelo de IA) | [TELEGRAM.md](TELEGRAM.md), ADR-011, ADR-016 |
| IA local | Ollama, **somente leitura**, sem ferramentas, só os dados do próprio usuário; sem caminho para iniciar ou aprovar ações | ADR-013 |
| Aprovação de ações | **PIN de 6 dígitos** criado no painel (exige a senha da conta), guardado como HMAC; PINs óbvios recusados; 5 erros travam por 15 min. O **código de 8 dígitos por e-mail** continua como alternativa quando não há PIN configurado | ADR-016 (adendo), `app/auth/action_pin.py` |
| Ações com aval | Catálogo fechado: `send_file`, `lock_screen`, `webcam_photo`, `network_scan`. Cada agente opta explicitamente em cada ação (`allowed_actions` no `config.json`; vazio = nenhuma). O backend assina um digest canônico (`aval-action-v1`) e o agente só executa se o digest bater, sem shell | ADR-015, ADR-016, ADR-020, `app/devices/commands.py` (`ACTIONS`) |
| Ações pelo painel web | Paridade com o Telegram para `lock_screen`, `webcam_photo`, `network_scan`: `POST /devices/{id}/actions` pede e aprova com o PIN na mesma chamada; `GET` lê estado/resultado; foto por endpoint próprio. Mesmo núcleo e mesmo PIN, sem poder novo; comando do web tem `chat_id = NULL` e não vai ao Telegram | ADR-021, `app/api/v1/routes/device_actions.py` |
| Sensor de senha errada | Opcional e **desligado por padrão** (`AVAL_SENSORS=failed_login_photo`), **só Linux**: o agente lê `journalctl -f -o json`, e numa falha de autenticação tira uma foto e envia por `POST /devices/{id}/events` (JWS `aud bots-central:event:v1`). O texto do diário nunca sai do PC; só vai o nome do programa. Limite de 1 foto/min no agente e 5/10 min no servidor; foto entregue ao Telegram do dono e apagada | ADR-019, `agent/internal/sensors/failedlogin.go` |
| Painel de administração | Aba **Admin** só quando `/auth/me` responde `role: admin`; rotas `/api/v1/admin/*` com o mesmo erro de rota inexistente. Mostra saúde, contagens, lista de usuários, falhas recentes e histórico de todos; **ativa conta pendente** (`admin.user_activated`). Não vê arquivos/fotos, PINs/senhas nem executa ações | ADR-017, `app/admin/`, `app/api/v1/routes/admin.py` |
| Auditoria | Append-only (trigger no PostgreSQL), mesma transação da ação, sem segredos (nem PIN, nem rótulo, nem conteúdo) | `app/audit` |
| Agente | Linux e macOS (Intel e Apple Silicon); executor das ações do catálogo; instaladores com serviço | [agent/README.md](../agent/README.md) |
| Painel web | React: login, cadastro, recuperação, dispositivos, telemetria, gráfico ao vivo, vínculo do Telegram, PIN, ações, aba Admin | ADR-009, ADR-018, ADR-021 |
| Servidor | Compose só no Tailscale, HTTPS `*.ts.net`, backup diário | [deploy/README.md](../deploy/README.md) |

## Ações do catálogo (estado real)

| Ação | Executa no agente | Resultado | Web? |
|---|---|---|---|
| `send_file` | lê só a pasta compartilhada (`shared_dir`), sem symlink/hard link, até 10 MB | arquivo | não (precisa de nome de arquivo; fluxo próprio) |
| `lock_screen` | `loginctl lock-sessions` (Linux) / `pmset displaysleepnow` (Mac) | só status | sim |
| `webcam_photo` | `fswebcam` (Linux) / `imagesnap` (Mac), até 2 MB | foto | sim |
| `network_scan` | `nmap -sn` só nas redes IPv4 privadas das próprias interfaces, sub-redes ≤ 256 endereços | texto | sim |

Ações listadas no catálogo do ADR-016 mas **ainda não implementadas**: `unlock_screen`, `power`,
`ban`, `apt_check`, `apt_upgrade`, `vault_reveal`/`vault_delete`. Ver
[DISCREPANCIES-2026-10.md](DISCREPANCIES-2026-10.md).

## Validação

- CI em todo push/PR: backend (ruff, mypy, pytest com PostgreSQL 17, pip-audit), frontend
  (testes, lint, typecheck, build), agente (`go test -race`, `go vet`), gitleaks.
- Ponta a ponta local (2026-10-21, em `main`): agente Go real ↔ backend real via HTTP —
  pareamento, heartbeat com telemetria, envio de arquivo com hash assinado, recusas.
- As capacidades desta branch (PIN, ações `lock_screen`/`webcam_photo`/`network_scan`, web,
  telemetria ao vivo, sensor de senha errada, papéis) têm testes de unidade/integração no
  backend e no agente, mas **ainda não passaram pelo E2E com hardware real** desta branch.
- Agente testado num Mac real (Intel, 2026-10-21).

## Ainda não validado em produção

- Servidor de casa no ar (acesso pendente), Telegram e Gmail reais, Ollama real, instaladores
  no Mac e no Kali, câmera e `nmap` reais, `journalctl`/grupo `systemd-journal` para o sensor.

## Fora do escopo atual

App Flutter, acesso remoto (RustDesk), IA de e-mail, instalação de programas, agente Windows,
organizações com vários membros, sensor de senha errada no macOS. Ver [ROADMAP.md](ROADMAP.md).

## Riscos conhecidos (aceitos nesta fase)

- O e-mail é a raiz de confiança: recupera a senha, cria a conta e (sem PIN) aprova ações. A
  conta de e-mail precisa de 2FA.
- O PIN é digitado no mesmo celular do Telegram: protege contra celular desbloqueado/roubado,
  não contra quem também sabe o PIN.
- A aprovação é verificada no servidor; um servidor comprometido poderia aprovar sozinho.
  Mitigação futura: aprovação assinada no celular e verificada pelo agente.
- Uma conta de administrador roubada vê a lista de e-mails dos usuários (não vê conteúdo, PINs
  nem senhas). Mitigação: PIN e senha longos, sessão curta, acesso só pela rede Tailscale.
- Um agente comprometido pode mandar telemetria, scan ou fotos falsas, mas só para o dono, com
  os limites de taxa descritos.
- `ABUSE_CONTROL_HMAC_KEY` é reaproveitada (com domínios separados) para limites, reset,
  aprovação de comandos e PIN. A separação por HKDF proposta no ADR-016 (item 7) ainda não foi
  implementada.
- Servidor e backup na mesma casa; Tailscale gratuito é para uso não comercial.
- Detalhes em [THREAT_MODEL.md](THREAT_MODEL.md) e nos ADRs.
