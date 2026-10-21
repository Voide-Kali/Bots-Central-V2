# Roadmap — Bots Central V2

Versão 1 (2026-10-21). Substitui a ordem genérica de `BUILD_V2.md` como plano de entrega.
Decisões marcadas como **[ADR]** ainda precisam de um ADR próprio antes da implementação.

## Visão

Uma central para gerenciar os computadores da empresa pelo celular e por um programa de
computador, com segurança em primeiro lugar:

- ver dispositivos, presença e telemetria (CPU, RAM, disco, temperatura);
- receber alertas (ex.: senha errada no login, com foto da webcam quando houver);
- enviar arquivos do computador para o celular;
- acesso remoto à tela;
- uma **IA de dispositivos** que consulta e *propõe* ações;
- uma **IA de e-mail**, totalmente separada, que resume e-mails e rascunha respostas.

## Princípios

1. **Nada age sozinho.** Toda ação sobre um computador é proposta, passa pelo Security Gate e
   precisa de aprovação humana proporcional ao risco.
2. **A aprovação é verificada no próprio agente.** O celular assina a aprovação com uma chave
   guardada no hardware (Secure Enclave, liberada por Face ID). O agente confere essa assinatura;
   um servidor comprometido sozinho não consegue mandar ações.
3. **Separação de privilégios entre as IAs.** A IA de e-mail não tem credencial, ferramenta nem
   contexto que alcance os agentes. Conteúdo externo (e-mail, páginas web) nunca é instrução.
4. **Fatias verticais.** Cada marco entrega uma função completa (backend + agente + app),
   com o mesmo rigor de testes, em vez de fases microscópicas por camada.
5. **Custo quase zero** até haver receita.

## Decisões

| # | Decisão | Motivo |
|---|---|---|
| D1 | **Flutter** para celular (iOS) e programa de computador (macOS, depois Windows/Linux). O painel React atual fica como ponte até o app Flutter cobrir as mesmas funções, e então é aposentado. | Uma base de código para todas as telas; `local_auth` para Face ID; alinhado ao ADR-004. |
| D2 | **Servidor em casa** (SSD 256 GB, HD 10 TB, 16 GB RAM) com Linux, Docker Compose, PostgreSQL 17 e backend. | Custo zero; hardware suficiente para o início. |
| D3 | **Sem portas abertas na internet.** Acesso remoto ao servidor por rede privada **Tailscale**; HTTPS com certificado `*.ts.net`. Ver Riscos sobre o plano gratuito. | Funciona atrás de CGNAT; não exige domínio; reduz muito a superfície de ataque. |
| D4 | **Notificações no iPhone via ntfy** auto-hospedado (app oficial do ntfy no iPhone), avisando para abrir o app. Push nativo próprio só quando houver conta Apple Developer paga. | Push nativo (APNs) exige o programa pago da Apple (US$ 99/ano), fora do orçamento. |
| D5 | **App no iPhone instalado pelo Xcode** com Apple ID gratuito durante o desenvolvimento (reinstalar a cada 7 dias). | Custo zero. |
| D6 | **Agente para macOS e Linux primeiro**; Windows depois. | Dispositivos disponíveis: Mac, notebook Kali, servidor. |
| D7 | **IA com provedor trocável** (interface única). Começa local (Ollama no servidor, modelo pequeno) para consultas simples; API paga só se necessário. **[ADR]** | Orçamento; dados não saem de casa. |
| D8 | **Acesso remoto via RustDesk** com servidor próprio, integrado, não reimplementado. Atenção à licença AGPL. **[ADR]** | Construir do zero seria enorme e arriscado. |
| D9 | **Instalação de programas só por gerenciadores oficiais** (`brew`, `apt`, depois `winget`), com o nome exato do pacote mostrado na aprovação. Sem baixar instaladores de sites. | Cadeia de suprimentos é o principal vetor de malware. |

## Marcos

Cada marco tem branch(es) próprias, PR, CI verde no SHA exato e aprovação do responsável.

### M0 — Arrumação (em andamento)
- Mesclar #14 (dependências) e #13 (remoção do `nvpn/`).
- PR novo a partir de `review/mvp1-hardening-final` rebaseada na `main`; fechar #12.
- Apagar branches já integradas (`infra/mvp1-ci-gates`, `review/mvp1-agent-ci-fix`, `fix/agent-*`).
- Versionar o ADR-010 (protocolo do agente, JWS EdDSA).
- Encurtar `CURRENT_STATE.md` (histórico vai para `docs/HISTORY.md`); atualizar README; "MVP-1" → "Marco 1".
- Corrigir o teste instável do Device Center (`sessionGeneration` atualizado em `useEffect`).
- Tornar o repositório privado (após checar forks/colaboradores).

### M1 — Servidor de casa e dispositivos reais
- Instalar Linux no servidor; Compose com PostgreSQL 17 e backend; Tailscale; HTTPS `*.ts.net`.
- Backup diário cifrado do PostgreSQL no HD de 10 TB; teste de restauração.
- Agente no macOS: pasta de estado em `~/Library/Application Support`, serviço `launchd`, job `macos` no CI.
- Scripts E2E funcionando no Mac (Docker sem `sudo`, sem `/proc`).
- **Pronto quando:** Mac e Kali pareados e online no servidor de casa, acessando de fora pelo Tailscale.

### M2 — Security Gate (base)
- 2FA (TOTP) e **recuperação de conta**: redefinição de senha por e-mail + códigos de recuperação.
  Recuperar a conta revoga todas as sessões e **bloqueia ações remotas por um período de espera**.
- Auditoria durável (quem, o quê, quando, de onde; resultado).
- Níveis de risco: consulta (nenhuma confirmação), baixo (um toque), alto (biometria + detalhes).
- Motor de políticas: o que cada usuário pode fazer em cada dispositivo. **[ADR]**

### M3 — Telemetria
- Agente coleta CPU, RAM, disco, rede, uptime e temperatura (quando o hardware expõe).
- Backend guarda série temporal no PostgreSQL com retenção definida; painel mostra gráficos.

### M4 — App Flutter (iPhone + Mac)
- Login, lista de dispositivos, telemetria, pareamento, alertas.
- Contrato de sessão para cliente nativo (refresh sem cookie). **[ADR]**
- Chave do app no Secure Enclave, liberada por Face ID, para assinar aprovações. **[ADR]**
- Notificações via ntfy.

### M5 — Primeira ação remota: enviar arquivo
- Protocolo de comandos assinados servidor → agente, com aprovação assinada pelo celular. **[ADR]**
- Só pastas autorizadas, limite de tamanho, auditoria, cifrado em trânsito.

### M6 — Alerta de senha errada (+ foto)
- Política de uso definida e comunicada antes (LGPD). Eventos de login no macOS e Linux; foto
  só com permissão de câmera concedida e aviso visível.

### M7 — Acesso remoto (RustDesk)
- Servidor RustDesk no servidor de casa, acessível só pelo Tailscale; sessão exige aprovação de alto risco.

### M8 — Agente Windows
- Porta do `storage` (trava de arquivo), serviço do Windows, CI `windows`.

### M9 — IA de dispositivos
- Primeiro só consulta ("qual PC está mais quente?"); depois propõe ações que passam pelo Gate.

### M10 — IA de e-mail (isolada)
- Contas corporativas via OAuth; resumo com remetente real e link para o original; respostas só
  após revisão e aprovação. Sem acesso aos agentes.

### M11 — Instalação de programas
- Apenas `brew`/`apt`/`winget`; aprovação de alto risco; registro do pacote e versão instalados.

## Orçamento (até R$ 100 agora)

| Item | Custo |
|---|---|
| Servidor (hardware próprio), Linux, Docker, PostgreSQL, ntfy, RustDesk, Ollama | R$ 0 |
| Tailscale (plano gratuito) | R$ 0 — ver Riscos |
| App no iPhone via Xcode com Apple ID gratuito | R$ 0 |
| Energia elétrica do servidor ligado 24h | variável |
| Futuro: Apple Developer Program (push nativo, TestFlight) | US$ 99/ano |
| Futuro, opcional: domínio próprio | ~R$ 40/ano |

## Riscos e pendências

- **Plano gratuito do Tailscale é para uso não comercial.** Serve durante o desenvolvimento; no uso
  real pela empresa, migrar para plano pago ou para WireGuard/Headscale próprio. **[decidir antes do uso em produção]**
- **Servidor único em casa:** queda de energia/internet derruba tudo; backup local não protege de
  incêndio/roubo — considerar uma cópia cifrada fora de casa no futuro.
- **Ninguém domina o código ainda.** Tarefa contínua: "tour guiado" do código e testes de ataque ao próprio sistema.
- **Multi-aba no painel web:** duas abas renovando a sessão ao mesmo tempo podem disparar a detecção de replay.
- Perguntas em aberto: de quem são os computadores (empresa/funcionários/pessoais); quantas pessoas
  usarão; contas de e-mail corporativas ou pessoais.
