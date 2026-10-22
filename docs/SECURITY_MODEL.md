# Modelo de segurança

**Negar por padrão. Nada perigoso acontece sem o aval humano.**

## Princípios em vigor

1. **Identidades separadas.** Usuários: senha Argon2id + sessão no servidor (tokens opacos,
   só digests no banco). Dispositivos: chave Ed25519 gerada no aparelho, aprovada pelo dono
   comparando o fingerprint.
2. **Toda requisição de dispositivo é assinada** (JWS EdDSA, audiência fixa por finalidade) e
   consome uma sequência monotônica: replay é recusado.
3. **Ações só por comando tipado + segundo fator.** O dono pede; um código vinculado àquela ação
   chega por e-mail; só então o agente recebe o comando. O agente valida tudo de novo
   localmente (pasta compartilhada, sem symlink/hard link, tamanho).
4. **Separação de privilégios entre IAs.** A IA de dispositivos não tem ferramentas; a futura IA
   de e-mail não terá acesso aos agentes. Conteúdo externo nunca é instrução.
5. **Menor exposição.** Servidor só na rede Tailscale; banco em rede Docker interna; CORS
   desligado (same-origin); agente como usuário sem privilégios.
6. **Auditoria append-only** de toda ação sensível, sem segredos.
7. **Segredos** só em variáveis de ambiente do servidor; logs redigem padrões de credencial.
8. **Respostas genéricas** onde a resposta poderia revelar se uma conta existe.

## Segurança proporcional

Controles baratos que evitam desastres são obrigatórios. Controles caros (aprovação assinada
no celular, passkeys, motor de políticas fino) estão no roadmap para quando houver usuários
reais. Lista e riscos aceitos em [ROADMAP.md](ROADMAP.md) e [CURRENT_STATE.md](CURRENT_STATE.md).

## Regras para qualquer mudança

Mudanças em autenticação, identidade de dispositivo, autorização, revogação, protocolo do
agente ou auditoria exigem ADR ou aprovação explícita do responsável, e revisão por alguém
(pessoa ou IA) diferente de quem escreveu.
