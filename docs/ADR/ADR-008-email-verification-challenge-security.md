# ADR-008: Email Verification Challenge Security

Status da decisão: aceita.

Status de implementação: migration `0003`, materiais, emissão/consume e boundary HTTP de verificação de e-mail foram implementados no MVP-1. Rotação operacional e outros domínios de challenge permanecem futuros.

## Decisão

Usar uma tabela específica `email_verification_challenges`, e não uma tabela genérica
para recovery, login suspeito ou mudanças críticas. A Fase 2B.4A cobre exclusivamente
uma conta `pending_verification` e seu `UserEmail` não verificado; os outros fluxos
trazem vínculos e requisitos de sessão/Gate incompatíveis.

Cada challenge tem exatamente um material: link de alta entropia ou código humano.
Ordem de lock obrigatória neste domínio: `UserEmail` → `User` →
`EmailVerificationChallenge`. Emissão/resend começa no `UserEmail`; consume faz lookup
inicial não confiável e depois adquire a mesma ordem antes de revalidar. Essa ordem não
governa domínios ainda não desenhados. A transição de e-mail/conta ocorre na mesma
transação. O contrato completo está em [EMAIL_VERIFICATION.md](../EMAIL_VERIFICATION.md).

## Consequências

A migration `0003` criou enums, tabela, constraints e índices específicos. Fluxos futuros podem criar tabelas próprias ou
uma abstração comum somente após requisitos concretos e nova decisão arquitetural.
