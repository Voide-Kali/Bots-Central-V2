# Documentação — Aval (Bots Central V2)

Índice da documentação do projeto. A fonte da verdade sobre o que funciona hoje é
[CURRENT_STATE.md](CURRENT_STATE.md); as decisões ficam nos ADRs em [ADR/](ADR/).

## Comece por aqui

| Documento | O que é |
|---|---|
| [CURRENT_STATE.md](CURRENT_STATE.md) | Estado atual do sistema: o que funciona, o que está validado e o que ainda não foi testado em produção. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Visão de arquitetura: componentes (backend, agente, painel, bot) e regras de fronteira. |
| [SECURITY_MODEL.md](SECURITY_MODEL.md) | Modelo de segurança: princípios em vigor (negar por padrão, aval humano, identidades separadas). |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Threat model: atores, superfícies de ataque, mitigações e riscos aceitos. |
| [ROADMAP.md](ROADMAP.md) | Plano de entrega, princípios, orçamento e o que fica para depois da demo. |

## Conta, autenticação e banco

| Documento | O que é |
|---|---|
| [AUTH.md](AUTH.md) | Referência detalhada de autenticação, sessões, reautenticação e identidade de dispositivos. |
| [REGISTRATION.md](REGISTRATION.md) | Fluxo de cadastro de conta. |
| [EMAIL_VERIFICATION.md](EMAIL_VERIFICATION.md) | Verificação de e-mail por código e segurança do desafio. |
| [PASSWORD_SECURITY.md](PASSWORD_SECURITY.md) | Hashing de senha (Argon2id) e políticas associadas. |
| [DATABASE.md](DATABASE.md) | Esquema do banco, migrations e papéis de acesso. |

## Dispositivos, interfaces e operação

| Documento | O que é |
|---|---|
| [DEVICE_ONLINE_V01.md](DEVICE_ONLINE_V01.md) | Contrato "Device Online V0.1": pareamento, heartbeat assinado e presença online/offline. |
| [TELEGRAM.md](TELEGRAM.md) | Interface do bot do Telegram: vínculo, menus, alertas e ações. |
| [LOCAL_E2E.md](LOCAL_E2E.md) | Como rodar o teste ponta a ponta local (agente Go real contra o backend real). |

## Revisões, histórico e inventários

| Documento | O que é |
|---|---|
| [SECURITY_REVIEW_2026-10.md](SECURITY_REVIEW_2026-10.md) | Revisão de segurança de outubro de 2026. |
| [DISCREPANCIES-2026-10.md](DISCREPANCIES-2026-10.md) | Diferenças entre a branch de features e o que já está na `main` (ações ainda não implementadas). |
| [LEGACY-INVENTORY.md](LEGACY-INVENTORY.md) | Inventário do código e das decisões herdadas da V1. |
| [HISTORY.md](HISTORY.md) | Histórico (diário antigo) do projeto. |
| [PRODUCT.md](PRODUCT.md) | Nota de produto herdada da fase inicial — desatualizada; use CURRENT_STATE.md e ROADMAP.md. |
| [BUILD_V2.md](BUILD_V2.md) | Plano de build inicial — substituído pelo [ROADMAP.md](ROADMAP.md). |

## Decisões de arquitetura (ADR)

Registros em [ADR/](ADR/). O ADR-010 (protocolo do agente, JWS EdDSA) foi aprovado mas ainda
não está versionado.

| ADR | Decisão |
|---|---|
| [ADR-001](ADR/ADR-001-python-fastapi.md) | Backend em Python + FastAPI. |
| [ADR-002](ADR/ADR-002-postgresql.md) | PostgreSQL como banco principal. |
| [ADR-003](ADR/ADR-003-go-agents.md) | Go para os agentes. |
| [ADR-004](ADR/ADR-004-flutter-mobile.md) | Flutter para o app mobile futuro. |
| [ADR-005](ADR/ADR-005-versioned-api.md) | API versionada desde o início. |
| [ADR-006](ADR/ADR-006-authentication-session-strategy.md) | Estratégia de autenticação e sessões. |
| [ADR-007](ADR/ADR-007-reauthentication-security-gate.md) | Reautenticação como portão de segurança. |
| [ADR-008](ADR/ADR-008-email-verification-challenge-security.md) | Segurança do desafio de verificação de e-mail. |
| [ADR-009](ADR/ADR-009-web-frontend-stack.md) | Stack do painel web: React, TypeScript e Vite. |
| [ADR-011](ADR/ADR-011-telegram-interface-email-approval.md) | Telegram como interface conversacional e código por e-mail como fator de aprovação. |
| [ADR-012](ADR/ADR-012-heartbeat-telemetry.md) | Telemetria de sistema dentro do heartbeat assinado. |
| [ADR-013](ADR/ADR-013-local-read-only-assistant.md) | Assistente de IA local, somente leitura, no Telegram. |
| [ADR-014](ADR/ADR-014-password-reset.md) | Recuperação de senha por código de e-mail. |
| [ADR-015](ADR/ADR-015-approved-file-transfer.md) | Primeira ação remota: enviar arquivo, aprovado por código de e-mail. |
| [ADR-016](ADR/ADR-016-approved-actions.md) | Ações com aval: modelo único para tudo que muda o computador (PIN de 6 dígitos). |
| [ADR-017](ADR/ADR-017-roles-admin.md) | Papéis "usuário" e "administrador". |
| [ADR-018](ADR/ADR-018-live-telemetry.md) | Telemetria ao vivo (1 por segundo) enquanto o dono olha. |
| [ADR-019](ADR/ADR-019-failed-login-photo.md) | Foto automática quando alguém erra a senha do computador. |
| [ADR-020](ADR/ADR-020-network-scan-action.md) | Ação com aval "ver quem está na rede" (network_scan). |
| [ADR-021](ADR/ADR-021-web-action-control.md) | Controle de ações pelo painel web. |
| [ADR-022](ADR/ADR-022-battery-telemetry.md) | Nível de bateria na telemetria e alerta de bateria fraca. |
| [ADR-023](ADR/ADR-023-assistant-context-and-events.md) | IA com contexto curto e leitura de eventos recentes. |
| [ADR-024](ADR/ADR-024-email-notify.md) | Aviso e resumo de e-mails novos (leitura). |
| [ADR-025](ADR/ADR-025-session-idle-timeout.md) | Tempo de inatividade da sessão (logout em 1 hora). |
| [ADR-026](ADR/ADR-026-download-site.md) | Site de download e instaladores sem terminal. |
| [ADR-027](ADR/ADR-027-public-download-page.md) | Página de download pública (só `/baixar`), via Tailscale Funnel. |
| [ADR-028](ADR/ADR-028-deb-installer.md) | Instalador Linux em `.deb` (clique duplo, sem terminal). |
| [ADR-029](ADR/ADR-029-landing-site.md) | Landing animada na página pública `/baixar`. |
| [ADR-030](ADR/ADR-030-public-full-exposure.md) | Exposição pública do sistema inteiro (risco aceito, pré-feira). |
| [ADR-031](ADR/ADR-031-funnel-owns-443.md) | Funnel é o único dono da porta 443 (corrige o conflito com o web). |
| [ADR-032](ADR/ADR-032-db-least-privilege.md) | Papel de banco com menos privilégio para backend e bot. |
| [ADR-033](ADR/ADR-033-encrypted-backups.md) | Backups do banco cifrados (age). |
