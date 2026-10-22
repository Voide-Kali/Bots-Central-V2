# Inventário do sistema antigo (Kali Bunker / Bots Central v1) → Aval

Data: 21/10/2026. Fontes lidas: `Voide-Kali/Bots-Central` (versão final, pasta `Ativos/`) e
`Voide-Kali/kali-bunker-bots` (versão intermediária; inclui o `lembrete-bot`). Os dois têm
praticamente o mesmo código (cerca de 22 mil linhas).

**Objetivo deste documento:** não perder nenhuma ideia boa do sistema antigo e decidir, uma por
uma, **se** ela entra no Aval e **como**, sem repetir a bagunça. Cada linha tem um veredito:

- ✅ **Trazer**: entra como está (só interface ou leitura, sem novo poder sobre o computador).
- 🔐 **Trazer com aval**: entra, mas só executa depois do código por e-mail (como o envio de
  arquivo, ADR-015). Precisa de um ADR antes de programar.
- ⏸️ **Depois**: boa ideia, mas não cabe até a apresentação de 30/11.
- ❌ **Não trazer**: contradiz o princípio do Aval ("nada acontece sem o seu aval") ou é
  arriscado demais para o ganho.

## 1. Por que o sistema antigo virou bagunça (para não repetir)

| Problema no antigo | Como o Aval evita |
|---|---|
| Dois bots Telegram com o **mesmo token** (`gmail-telegram-bot` e `kali-bunker-telegram`), e era proibido ligar os dois juntos | Um único processo de bot (`app.telegram.bot`), um token só |
| Lógica espalhada: `bot.py` com 3.339 linhas, `remote_control.py` com 1.992 e `telegram_control.py` com 1.598, fazendo coisas parecidas | Módulos pequenos por assunto (`app/telegram/*`, `app/devices/*`, `app/assistant/*`) |
| Estado em vários arquivos JSON e SQLite soltos na home | Tudo no PostgreSQL, com migrations (Alembic) e backup diário |
| Agente falava com o servidor **por SSH** e uma fila SQLite | Agente Go com identidade própria (Ed25519) e mensagens assinadas (JWS) por HTTPS, só pelo Tailscale |
| A IA podia propor **comando de terminal** e a "confirmação" era um código no mesmo chat (o próprio SECURITY.md admitia: "confirmação no mesmo chat não é segundo fator") | A IA não tem ferramentas; ação real só com código **por e-mail** (outro canal) |
| Muitos `.env` e flags (`REMOTE_*_ENABLED`) | Um `.env` gerado por script, segredos só no servidor |
| Credencial vazou dentro de um PDF publicado (incidente de 03/08/2026) | `gitleaks` no CI em todo PR |

## 2. Inventário por módulo

### 2.1 Painel e Telegram (`gmail-telegram/bot.py`, `kali-bunker/telegram_control.py`)

| Ideia do antigo | Veredito | No Aval |
|---|---|---|
| Menu principal com botões (Painel, IA, Serviços, Rede, Cofre, Pendentes, Terminal, Arquivo) | ✅ | Menu fixo: Painel, IA, Histórico, Arquivo, Ajuda (PR #38) |
| Cartão "MEU PC" (online/offline, visto há, IPs, CPU, RAM, disco, serviços) com botões Atualizar/Voltar | ✅ | Cartão por computador (PR #38). IPs e "serviços ativos" ⏸️ depois |
| Editar a mesma mensagem ao apertar botão (`edit_or_reply`) em vez de mandar outra | ✅ | Próximo passo do bot (menos poluição no chat) |
| `/historico` de ações | ✅ | Já existe (auditoria append-only) |
| `/resumo`, `/relatorio`, relatório diário às 9h | ✅ | Relatório diário opcional no Telegram (CPU/RAM/disco/temperatura de cada PC) |
| Alertas inteligentes: CPU > 90%, disco > 90%, temperatura > 82 °C sustentados por 3 min, com cooldown de 30 min | ✅ | Regra no servidor sobre a telemetria que já chega |
| Alerta de bateria baixa (25%) | ✅ | Agente passa a mandar bateria (só leitura) |
| Avisar quando o PC liga e desliga (boot/shutdown) | ✅ | Já existe como online/offline; dá para melhorar o texto |
| Silenciar alertas por X horas / modo manutenção | ✅ | Botão "Silenciar 1 h / 8 h" |
| Desligar, reiniciar, suspender o PC | 🔐 | Ação com aval por e-mail (ADR novo) |
| Bloquear a tela | 🔐 | Ação com aval (risco baixo, útil na demo) |
| Desbloquear a tela remotamente | 🔐 | Decisão do Voide (21/10): entra, com aval por e-mail e registro no histórico |
| Foto da webcam | 🔐 | Ação com aval; foto vai só para o seu Telegram |
| Scan de rede (`nmap -sn`) | 🔐 | Ação com aval, somente "quem está na minha rede" |
| Controlar serviços (start/stop/restart de uma lista) | ⏸️ | Talvez com aval, depois |
| `/logs` de um serviço | ⏸️ | Depois |
| Terminal / `/cmd` (rodar comando livre) | ❌ | É o oposto do Aval; a pesquisa mostra por quê |
| Instalar pacote pela **IA** | ❌ | A IA não propõe ações. Instalar um pacote **pelo menu**, com nome validado, 🔐 com aval |
| `/atualizar` (ver atualizações e apt upgrade) | 🔐 | Decisão do Voide: entra com aval; só os comandos fixos `apt list --upgradable` e `apt upgrade -y` |
| Modo emergência (bloquear + reiniciar módulos) | ⏸️ | Rever quando houver as ações com aval |
| Banir IP/MAC no firewall pelo Telegram | 🔐 | Decisão do Voide: entra com aval; nunca bane o IP do Tailscale do servidor nem o gateway |
| Cofre de senhas no Telegram | 🔐 | Decisão do Voide: entra. Cofre cifrado no PC (como `voice_vault.py`), revelar exige aval por e-mail, mensagem com autodestruição. Risco aceito: a senha revelada passa pelo Telegram |
| Lista de "pendentes" com Confirmar/Cancelar | ✅ | Pedidos de aval pendentes com botão Cancelar (aprovar continua só com o código do e-mail) |
| Apagar mensagens sensíveis do chat | ✅ | Útil para o código de vínculo |

### 2.2 IA ("Voz", `remote_control.py`)

| Ideia | Veredito | No Aval |
|---|---|---|
| Conversa com a IA no Telegram | ✅ | Já existe (Ollama local, sem ferramentas) |
| Respostas locais rápidas sem IA (porcentagem, regra de três, conversões, senha forte) | ⏸️ | Depois; não é o foco |
| Plano de estudos, resumo, quiz | ⏸️ | Fica para o "bot de estudos" (abaixo) |
| Memória curta da conversa | ✅ | Guardar as últimas 3 trocas, só para contexto |
| Memória permanente ("lembre que…") | ⏸️ | Depois, com cuidado: memória é vetor de prompt injection persistente |
| IA propõe ação → "pendente" → confirma no chat | ❌ (como era) | No Aval a IA **nunca** propõe ação executável |
| Áudio/voz transcrito (Whisper) | ⏸️ | Bom para depois (whisper.cpp local) |
| Ler PDF/arquivos enviados no chat | ⏸️ | Depois; também é vetor de injection, ótimo para a pesquisa |

### 2.3 Agente no PC (`pc_agent.py`, `pc_bridge.py`, `action_policy.py`)

| Ideia | Veredito | No Aval |
|---|---|---|
| Fila persistente de tarefas com "lease" (não executar duas vezes) | ✅ (já feito) | `device_commands` no PostgreSQL (ADR-015) |
| Política determinística com lista branca de ações e parâmetros exatos (`action_policy.py`) | ✅ | Mesma ideia: cada ação nova é um tipo fechado, sem texto livre |
| Digest canônico da ação (o que foi aprovado é exatamente o que executa) | ✅ | Usar no ADR das ações com aval |
| Telemetria com IPs e estado de serviços | ⏸️ | IPs: depois (dado sensível); serviços: depois |
| Enviar arquivo/pasta (compacta pasta em `.tar.gz`) | ✅ parcial | Arquivo único da pasta compartilhada já existe; pasta ⏸️ |
| Transporte por SSH | ❌ | Substituído por HTTPS assinado |

### 2.4 Sensores de segurança do Kali (`bluetooth_alarm.py`, `monitor-*.py`, `network-watch.sh`)

| Ideia | Veredito | No Aval |
|---|---|---|
| **Foto de quem errou a senha** (`monitor-auth.py`) | 🔐/⏸️ | Era um dos seus pedidos. Vira um "sensor" opcional do agente que avisa no Telegram; a foto vai junto só se você ativar na instalação |
| Dispositivo desconhecido entrou no Wi-Fi (`monitor-wifi.py`, MACs conhecidos) | ⏸️ | Ótimo alerta; precisa de `arp-scan`/root no PC |
| Alarme de proximidade Bluetooth (iPhone longe → bloqueia tela e USB) | ⏸️ | Específico do Kali; manter no Kali Bunker por enquanto |
| Monitor de acesso à pasta Documentos (inotify) | ⏸️ | Depois |
| CPU/RAM alto com top de processos | ✅ | Entra nos alertas inteligentes (2.1) |
| Fail2Ban, USBGuard | ❌ no Aval | São ferramentas do sistema operacional; continuam instaladas no Kali, fora do Aval |

### 2.5 Operação (`bunkerctl.py`, `bunker_health.py`, `runtime_integrity.py`, `install.sh`)

| Ideia | Veredito | No Aval |
|---|---|---|
| Watchdog que vigia os próprios serviços e avisa falha/recuperação | ✅ | Alerta quando backend, bot ou banco caem (healthcheck do Docker + aviso no Telegram) |
| `doctor` / checklist pós-instalação | ✅ | Script `deploy/server/doctor.sh` (Tailscale, portas, .env, Gmail, Telegram, Ollama) |
| Backup com `.env` redigido e rotação | ✅ parcial | Backup diário do banco já existe; rotação já existe |
| Manifesto SHA-256 do runtime instalado | ⏸️ | Ideia boa para o agente; depois |
| Relatório HTML | ⏸️ | O painel já cumpre esse papel |
| Varredura de segredos antes de publicar (`prepublish_check.py`) | ✅ (já feito) | `gitleaks` no CI |
| Limpeza semanal automática | ❌ | Fora do escopo |

### 2.6 Gmail (`gmail_client.py`, `db.py`, `summarizer.py`)

| Ideia | Veredito | No Aval |
|---|---|---|
| Monitorar várias contas Gmail e avisar no Telegram | ⏸️ | É a "IA de e-mail separada" do roadmap. Entra **depois** da feira, como serviço próprio |
| Caixa de saída durável (não perder nem duplicar aviso após reinício) | ✅ (ideia) | Mesmo padrão quando o Gmail entrar |
| Resumo por IA só com opção explícita (privacidade) | ✅ (ideia) | Resumo com IA **local** (Ollama); e-mail não sai do servidor |
| Gravar só o ID opaco da mensagem, nunca o conteúdo | ✅ (ideia) | Igual |

### 2.7 Estudos e Lembretes (`estudos/`, `lembrete-bot/`)

| Ideia | Veredito | No Aval |
|---|---|---|
| Resumo, questões e flashcards de PDF (Gemini/Groq) | ⏸️ | Fora do Aval; continua como bot separado |
| Lembretes em linguagem natural com adiar por botão | ⏸️ | Fora do Aval; bot separado |

## 3. Ordem proposta

**Até a apresentação (30/11), só o que reforça a demo e a pesquisa:**

1. Telegram com menu, botões e cartões (PR #38) e edição da mesma mensagem.
2. Alertas inteligentes (CPU, disco, temperatura e bateria) com silenciar.
3. Watchdog do próprio Aval e `doctor.sh`.
4. ADR-016 "Ações com aval": bloquear/desbloquear tela, foto da webcam, desligar/reiniciar,
   scan da rede, banir IP/MAC, apt e cofre, todas com código por e-mail, lista branca e
   digest canônico. Implementar só depois da sua aprovação, uma ação por PR.
5. Sensor "senha errada → aviso (+ foto opcional)", dentro do ADR-016.

**Depois da feira:** Gmail como serviço separado, Wi-Fi desconhecido, memória da IA, áudio, IPs e
serviços na telemetria, e Windows.

**Nunca (decisão do Voide em 21/10):** terminal remoto (comando livre) e qualquer ação proposta pela
IA. Cofre, desbloquear tela, banir IP/MAC e apt entram como ações com aval (ADR-016).
