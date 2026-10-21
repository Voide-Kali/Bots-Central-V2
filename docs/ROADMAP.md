# Roadmap — Bots Central V2

Versão 2 (2026-10-21). Substitui a ordem genérica de `BUILD_V2.md` como plano de entrega.
Decisões marcadas como **[ADR]** ainda precisam de um ADR próprio antes da implementação.

## Visão

Uma central para gerenciar computadores pelo celular, com segurança em primeiro lugar:

- ver dispositivos, presença e telemetria (CPU, RAM, disco, temperatura);
- receber alertas (ex.: dispositivo offline; no futuro, senha errada com foto da webcam);
- conversar com uma **IA de dispositivos** que consulta e *propõe* ações;
- enviar arquivos do computador para o celular;
- no futuro: acesso remoto, app próprio, **IA de e-mail** separada.

Objetivo de curto prazo: **demonstração para feiras de ciência** (FETEC e outras), com o tema
de pesquisa *"como permitir que uma IA atue sobre computadores sem poder ser manipulada"*.

## Princípios

1. **Nada perigoso acontece sem aprovação humana** proporcional ao risco.
2. **Separação de privilégios entre as IAs.** A IA de e-mail (futura) não tem credencial,
   ferramenta nem contexto que alcance os agentes. Conteúdo externo nunca é instrução.
3. **Segurança proporcional.** Manter os controles baratos que evitam desastres; adiar os caros
   até haver usuários reais. Ver a seção abaixo.
4. **Fatias verticais.** Cada entrega é uma função completa (agente + backend + interface).
5. **Custo zero** até haver receita.

## Segurança proporcional

**Obrigatório sempre:**
- servidor sem portas abertas na internet (acesso só via Tailscale);
- senhas Argon2id e tokens persistidos só como digest (já implementado);
- ação de alto risco só com código de aprovação por e-mail vinculado à ação;
- bot do Telegram responde só a contas vinculadas;
- segredos fora do código e do Git;
- auditoria de ações (quem, o quê, quando, resultado);
- backup do banco.

**Adiado até haver usuários reais ou orçamento:**
- aprovação assinada no celular e verificada pelo agente (proteção contra servidor comprometido);
- passkeys/WebAuthn;
- motor de políticas fino (começar com papéis: dono, admin, leitura);
- matrizes de teste exaustivas em cada função nova: cobrir caminho normal e ataques óbvios.

## Decisões

| # | Decisão | Motivo |
|---|---|---|
| D1 | **Telegram é a interface do usuário nesta fase** (alertas, consultas, IA). Ver ADR-011. | Intuitivo, grátis, notificações funcionam no iPhone sem conta Apple paga. |
| D2 | **Código de aprovação por e-mail** para ações de alto risco, digitado no Telegram. Ver ADR-011. | Dois canais independentes; reaproveita a verificação de e-mail existente. |
| D3 | **Painel web React** continua para administração (pareamento, aprovação de dispositivos). | Já existe e funciona. |
| D4 | **App Flutter** (iOS/macOS) fica para quando houver orçamento para o Apple Developer Program. | US$ 99/ano fora do orçamento atual; ADR-004 continua válido. |
| D5 | **Servidor em casa**: Ubuntu Server (SSD 256 GB NVMe, HD 1 TB, 16 GB RAM), Docker Compose, PostgreSQL 17. | Custo zero; hardware suficiente. |
| D6 | **Sem portas abertas**: acesso pela rede **Tailscale**; HTTPS `*.ts.net`. | Funciona atrás de CGNAT; sem domínio; pequena superfície de ataque. |
| D7 | **IA local com Ollama** no servidor, atrás de uma interface trocável. Começa só com consultas. **[ADR]** | Custo zero; dados não saem de casa. |
| D8 | **Agente para macOS e Linux**; Windows depois (testar em PC da escola). | Dispositivos disponíveis: Mac, notebook Kali. |
| D9 | **Acesso remoto via RustDesk** auto-hospedado, quando chegar a hora. Licença AGPL. **[ADR]** | Não reimplementar. |
| D10 | **Instalação de programas só por gerenciadores oficiais** (`brew`, `apt`, `winget`). | Cadeia de suprimentos. |

## Equipe de IAs

| Papel | Ferramenta |
|---|---|
| Arquitetura, revisão e implementação na nuvem | Claude (chat) |
| Implementação local e servidor via SSH | Claude Code no Mac |
| Revisão independente de PR antes do merge | Gemini |
| Pentest do sistema rodando | Grok |
| Segunda opinião pontual | ChatGPT |

Regras: nenhuma IA aprova o próprio trabalho; nunca colar senhas, tokens ou `.env` em nenhuma IA;
o merge é sempre do responsável.

## Plano até 30/11/2026 (demo)

| # | Entrega | Pronto quando |
|---|---|---|
| 1 | **Arrumação**: mesclar #14, #13, #16 (hardening, substitui #12), #15 (este roadmap) | `main` com CI verde |
| 2 | **Servidor no ar**: Compose no Ubuntu, Tailscale, HTTPS, backup diário do banco | Mac e Kali pareados e online, acessando de fora |
| 3 | **Telemetria**: CPU, RAM, disco, temperatura no heartbeat assinado; painel mostra | Valores reais do Mac e do Kali no painel |
| 4 | **Bot do Telegram**: vínculo de conta, alertas online/offline, `/status` | Alerta chega no iPhone quando um PC desliga |
| 5 | **IA local no Telegram**: perguntas sobre dispositivos (só leitura) | "Qual PC está mais quente?" responde certo |
| 6 | **Auditoria + recuperação de conta**: registro de ações; redefinição de senha por e-mail + códigos de recuperação | Ações aparecem no histórico; senha esquecida é recuperável |
| 7 | **Ação aprovada por e-mail**: enviar arquivo de pasta autorizada | Pedido no Telegram → código no e-mail → arquivo chega |
| 8 | **Teste de ataque**: tentativas de prompt injection contra a IA (Grok como pentester), registradas | Relatório com tentativas e resultado |
| 9 | **Material da feira**: relatório, banner, roteiro de demo, vídeo de backup | Demo ensaiada de ponta a ponta |
| 10 | Meta extra: agente Windows (PC da escola) ou alerta de senha errada | Funciona em 1 dispositivo real |

Ordem semanal sugerida: semana 1 → itens 1–2; semana 2 → 3–4; semana 3 → 5–6; semana 4 → 7–8; semana 5 → 9–10.

Fora desta fase: app Flutter, acesso remoto, IA de e-mail, instalação de programas,
organizações com vários membros.

## Depois da demo

1. Organizações, membros e papéis; período de espera para ações remotas após recuperar a conta.
2. Foto em senha errada (com política de uso e aviso — LGPD).
3. Agente Windows.
4. Acesso remoto (RustDesk).
5. App Flutter + aprovação assinada no celular.
6. IA de e-mail isolada.
7. Instalação de programas por gerenciadores oficiais.

## Orçamento

| Item | Custo |
|---|---|
| Servidor (hardware próprio), Ubuntu, Docker, PostgreSQL, Ollama | R$ 0 |
| Tailscale (plano gratuito) | R$ 0 — ver Riscos |
| Bot do Telegram, Gmail do sistema (senha de app) | R$ 0 |
| Energia do servidor 24h | variável |
| Futuro: Apple Developer Program | US$ 99/ano |

## Riscos e pendências

- **Prazo (~6 semanas, noites):** itens 1–5 são o núcleo; 6–9 completam a demo; 10 é extra.
- **Tailscale gratuito é para uso não comercial:** adequado ao desenvolvimento e à feira; rever
  antes de uso comercial (plano pago ou WireGuard/Headscale).
- **Servidor único em casa via Wi-Fi:** preferir cabo; backup local não protege de roubo/incêndio.
- **Código escrito por IA:** o responsável precisa conseguir explicar cada parte na feira e
  declarar o uso de IA conforme as regras de cada evento. Fazer "tour guiado" do código.
- **IA local em CPU com 16 GB:** usar modelo pequeno; se ficar lento demais, reavaliar.
- **Repositório público:** tornar privado em breve.
- **Nome do projeto:** provisório; escolher nome definitivo antes da feira.
