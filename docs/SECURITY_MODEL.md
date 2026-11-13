# Modelo de seguranca

**Negar por padrao. Nada perigoso acontece sem o aval humano.**

## Principios em vigor

1. **Identidades separadas.** Usuarios: senha Argon2id + sessao no servidor (tokens opacos,
   so digests no banco). Dispositivos: chave Ed25519 gerada no aparelho, aprovada pelo dono
   comparando o fingerprint.
2. **Toda requisicao de dispositivo e assinada** (JWS EdDSA, audiencia fixa por finalidade) e
   consome uma sequencia monotonica: replay e recusado.
3. **Acoes so por comando tipado + segundo fator.** O dono pede; aprova com o **PIN pessoal de 6
   digitos** (ADR-016; HMAC com subchave HKDF dedicada — ADR-038; 5 erros travam por 15 min);
   so entao o agente recebe o comando. O agente valida tudo de novo localmente (digest canonico
   `aval-action-v1`, pasta compartilhada, sem symlink/hard link, tamanho). O codigo por e-mail
   continua para cadastro e recuperacao de senha.
4. **Separacao de chaves HMAC.** HKDF (SHA-256) com dominios separados por finalidade:
   `aval/rate-limit/v1`, `aval/reset-code/v1`, `aval/approval-code/v1`, `aval/action-pin/v1`.
   Flag-day executado (migracao 0024); PINs antigos invalidados (ADR-038).
5. **Catalogo fechado de acoes.** Tanto no backend (`ACTIONS dict`) quanto no agente
   (`KnownActions map`), o catalogo e explicito e fechado. Nao ha shell, nao ha texto livre.
   Cada acao tem programa e argumentos fixos. O agente opta em cada acao individualmente
   (`allowed_actions` no `config.json`; vazio = nenhuma).
6. **Separacao de privilegios entre IAs.** A IA de dispositivos nao tem ferramentas; conteudo
   externo nunca e instrucao.
7. **Menor exposicao.** Servidor so na rede Tailscale; banco em rede Docker interna; CORS
   desligado (same-origin); CSP restritiva (sem `unsafe-inline` no script-src); agente como
   usuario sem privilegios.
8. **Auditoria append-only** de toda acao sensivel, sem segredos (`_FORBIDDEN_DETAIL_KEYS`
   impede tokens, codes, passwords, secrets, keys, jws e proofs nos detalhes). Timestamp por
   `clock_timestamp()` do PostgreSQL.
9. **Segredos** so em variaveis de ambiente do servidor; logs redigem padroes de credencial.
10. **Respostas genericas** onde a resposta poderia revelar se uma conta existe.

## Token de acesso

O access token e mantido **so em memoria** no frontend (`memoryAccessToken.ts`): nunca toca
localStorage, sessionStorage ou cookie. Perdido ao recarregar a pagina (seguro por design).
O refresh e feito pelo cookie HttpOnly com `credentials: "same-origin"`.

## Seguranca proporcional

Controles baratos que evitam desastres sao obrigatorios. Controles caros (aprovacao assinada
no celular, passkeys, motor de politicas fino) estao no roadmap para quando houver usuarios
reais. Lista e riscos aceitos em [ROADMAP.md](ROADMAP.md) e [CURRENT_STATE.md](CURRENT_STATE.md).

## Regras para qualquer mudanca

Mudancas em autenticacao, identidade de dispositivo, autorizacao, revogacao, protocolo do
agente ou auditoria exigem ADR ou aprovacao explicita do responsavel, e revisao por alguem
(pessoa ou IA) diferente de quem escreveu.
