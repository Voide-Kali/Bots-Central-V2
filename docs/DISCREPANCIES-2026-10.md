# Discrepâncias a alinhar antes da apresentação (30/11/2026)

Levantamento feito em 2026-10-22 na branch `feat/web-actions` (reúne ADR-016 a ADR-021, ainda
não mescladas na `main`). Objetivo: separar o que o código já faz do que a documentação e os
rótulos de "disponível" afirmam, para a demo não prometer o que a `main` ainda não tem.

Convenção: **branch** = código em `feat/web-actions`; **main** = o que já está mesclado.

## 1. `CURRENT_STATE.md` estava preso ao estado antigo

O arquivo anterior (revisão 2026-10-21) descrevia só `send_file` como ação remota e listava
"foto em senha errada", "papéis" e "controle pelo web" como fora do escopo. Na branch, todos
existem. O `CURRENT_STATE.md` foi reescrito para o estado real desta branch; este item fica
registrado porque a **main ainda reflete o estado antigo** até o merge das pilhas.

## 2. "PIN" vs "código por e-mail"

- **Doc antiga / ADR-015 / SECURITY_MODEL.md:** o segundo fator das ações é o **código de 8
  dígitos por e-mail** digitado no Telegram.
- **Código (branch):** o segundo fator primário das ações do catálogo é o **PIN de 6 dígitos**
  criado no painel (`app/auth/action_pin.py`, `PIN_DIGITS = 6`). O código por e-mail
  (`app/devices/commands.py`, `CODE_DIGITS = 8`) continua como **alternativa quando não há PIN
  configurado**, e segue sendo o fator de **cadastro e recuperação de senha**.
- Ambos os caminhos coexistem: `commands.approve` (código por e-mail, comando com `approval_mac`)
  e `commands.approve_with_pin` (PIN, comando com `approval_mac = NULL`).
- **A alinhar:** `SECURITY_MODEL.md` (princípio 3, "um código ... chega por e-mail") e o ADR-015
  descrevem só o e-mail. O ADR-016 já traz o adendo do PIN, mas os dois documentos de base não.
  Roteiro de demo e site devem dizer "PIN (ou código por e-mail)".

## 3. Catálogo do ADR-016 maior que o implementado

O ADR-016 define um catálogo com `lock_screen`, `unlock_screen`, `webcam_photo`, `power`,
`network_scan`, `ban`, `apt_check`, `apt_upgrade`, `vault_reveal`/`vault_delete`.

- **Implementado de fato** (`app/devices/commands.py`, dict `ACTIONS`, ~linhas 90-124; executor
  em `agent/internal/commands/actions.go` e `scan.go`): só `send_file`, `lock_screen`,
  `webcam_photo`, `network_scan`.
- **Não implementado:** `unlock_screen`, `power`, `ban`, `apt_check`, `apt_upgrade`,
  `vault_reveal`/`vault_delete`.
- O próprio ADR-016 prevê "implementação em PRs separados"; o estado atual cobre só os primeiros.
- **A alinhar:** nenhum rótulo de "disponível" (site, banner, roteiro) deve citar desligar/
  reiniciar, banir IP/MAC, atualizações `apt` ou cofre de senhas. Hoje são apenas: bloquear
  tela, foto da webcam, scan de rede e enviar arquivo.

## 4. Status "proposto" em ADRs já implementados

- `ADR-016`: **aprovado** (adendo). OK.
- `ADR-017`: **aprovado**. OK.
- `ADR-018`, `ADR-019`, `ADR-020`, `ADR-021`: cabeçalho ainda diz **"proposto em 22/10/2026"**,
  embora o código correspondente esteja implementado e testado nesta branch (rotas `/live` e
  `/watch`, `sensors/failedlogin.go`, `scan.go`, `routes/device_actions.py`).
- `ADR-016`, adendo item 3, chama a foto de senha errada de "próximo passo", mas o ADR-019 e o
  código já existem.
- **A alinhar:** ao mesclar, mudar o status desses ADRs para "aprovado/implementado" para não
  parecer que são ideias ainda não feitas.

## 5. ROADMAP: itens marcados como futuros que já foram entregues

No `ROADMAP.md`:

- "Adiado até haver usuários reais": **"motor de políticas ... começar com papéis: dono, admin,
  leitura"** — a parte de papéis foi entregue (ADR-017), porém só com `user` e `admin` (não há
  papel "leitura"). Atualizar o texto para refletir o que existe.
- Seção "Depois da demo", item 2: **"Foto em senha errada (com política de uso e aviso — LGPD)"**
  — entregue para Linux (ADR-019), opcional e desligado por padrão. O aviso de LGPD/uso ainda
  precisa aparecer no painel e no instalador (o próprio ADR-019 cobra isso).
- Plano até 30/11, item 10 (meta extra): **"alerta de senha errada"** — já implementado.
- **Telemetria ao vivo (1/s com gráfico)** e **controle de ações pelo painel web** não estavam
  no plano e foram entregues (ADR-018, ADR-021).
- **A alinhar:** anotar no ROADMAP que esses itens já foram feitos (sem reescrever o plano
  inteiro). O núcleo de curto prazo (servidor no ar, Telegram/Gmail reais) continua pendente.

## 6. `ARCHITECTURE.md` desatualizado

- Diz "Ver `docs/ADR/` (ADR-001 a ADR-015)" e "ADR-010 ... ainda não está versionado" — agora há
  ADRs até o **021**.
- A linha de `backend/app/devices` descreve "comandos aprovados (`send_file`)"; o módulo agora
  tem o catálogo de ações e eventos de dispositivo (`app/devices/events.py`).
- Não lista os módulos novos: `app/admin`, `app/auth/action_pin.py`, `app/devices/events.py`,
  `app/core/timezone.py`.
- **A alinhar:** atualizar a tabela de componentes e a contagem de ADRs (fora do escopo desta
  tarefa, que foca em `CURRENT_STATE`; anotado aqui).

## 7. `SECURITY_MODEL.md` desatualizado

- Princípio 3 descreve o segundo fator só como código por e-mail (ver item 2 acima).
- Não menciona os papéis `user`/`admin` (ADR-017) nem a superfície nova de autorização das rotas
  de ação pelo web (ADR-021), ambos mexendo em autorização.
- **A alinhar:** acrescentar o PIN como segundo fator e uma linha sobre papéis e rotas de admin.

## 8. Chave HMAC: separação por HKDF ainda não feita

O ADR-016 (item 7) propõe derivar chaves por HKDF por uso (`rate-limit`, `reset-code`,
`approval-code`, `vault-label`). No código, `ABUSE_CONTROL_HMAC_KEY` continua única, com
separação só por rótulo de domínio em `pseudonymize`, e agora também serve ao PIN. O risco
descrito no `CURRENT_STATE.md` permanece válido; registrado para não ser esquecido.

## Resumo para a demo

- Falar em "PIN (ou código por e-mail)", não só e-mail.
- Ações reais: **bloquear tela, foto da webcam, scan de rede, enviar arquivo** — e nada além.
- Deixar claro o que está na `main` vs. o que está em branch, caso a demo rode da `main`.
- O sensor de senha errada é **Linux, opcional e off por padrão**, e ainda falta o aviso de
  LGPD no painel/instalador.
