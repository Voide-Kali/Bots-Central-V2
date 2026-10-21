# ADR-014: Recuperação de senha por código de e-mail

Status: proposto (2026-10-21) — **exige aprovação explícita** (mudança de autenticação).

## Contexto

Sem recuperação, quem esquece a senha perde a conta. O e-mail principal verificado já é o
canal de confiança do cadastro (ADR-008) e o servidor já envia e-mail por SMTP STARTTLS.

## Decisão

1. `POST /api/v1/auth/password-reset/request {email}` responde **sempre** `202` com a mesma
   mensagem. Só conta `ACTIVE` com e-mail principal **verificado** e senha cadastrada recebe
   código. Envio em segundo plano, depois da resposta.
2. Código de **8 dígitos**, válido por **15 min**, uso único; pedir outro invalida o anterior.
   Só o HMAC-SHA-256 do código (chave `ABUSE_CONTROL_HMAC_KEY`, domínio próprio, ligado ao
   `user_id`) é guardado.
3. `POST /api/v1/auth/password-reset/confirm {email, code, new_password}`: política de senha
   validada antes de tudo; Argon2id calculado **antes** do lock e em toda tentativa (tempo
   uniforme); comparação em tempo constante; no máximo **5 erros por código** (contador
   commitado), depois o código morre.
4. No sucesso: nova hash, código consumido, `users.security_version += 1` (invalida todos os
   access/refresh tokens existentes), todas as sessões revogadas com motivo `password_reset` e
   **o vínculo do Telegram removido** (canal de contenção — revisão independente M2).
5. Limites (PostgreSQL, fail-closed): pedido 3/h por e-mail, 10/h por rede; confirmação 10/h por
   e-mail, 20/h por rede.
6. Auditoria: `auth.password_reset_requested`, `auth.password_reset_failed` (negado) e
   `auth.password_reset_completed`.

## Consequências

- Quem controla o e-mail controla a conta — mesmo modelo do cadastro. A conta de e-mail precisa
  de 2FA.
- 8 dígitos + 5 tentativas + 3 códigos/h por e-mail tornam adivinhação inviável
  (≈ 15 chances em 10⁸ por hora).
- Pendente (roadmap): período de espera para ações remotas logo após uma recuperação.
- Riscos aceitos nesta fase (revisão independente): (a) o pedido de código faz mais trabalho
  para contas existentes do que para inexistentes, uma diferença de tempo mensurável só com muitas
  redes e contida pelos limites; (b) a chave `ABUSE_CONTROL_HMAC_KEY` é reaproveitada com domínio
  próprio em vez de um keyring dedicado como no ADR-008 — rever quando houver rotação de chaves.
