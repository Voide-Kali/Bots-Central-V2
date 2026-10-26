# ADR-025: Tempo de inatividade da sessao (logout em 1 hora)

Status: **aceito em 23/10/2026**. Pedido do Voide: a conta ficava logada por dias; ele quer que,
passada uma hora fora do sistema, a sessao caia e exija login de novo.

## Contexto

A sessao tem tres limites (app/auth/authentication.py): o token de acesso (`ACCESS_TTL`, 10 min),
o teto absoluto da sessao (`SESSION_TTL`, 30 dias) e a janela de inatividade (`IDLE_TTL`). O
`IDLE_TTL` estava em **7 dias**: so depois de uma semana parada a sessao caia. Na pratica a conta
ficava logada "para sempre" no uso normal — risco se o computador fica aberto ou e de outra pessoa.

## Decisao

1. **IDLE_TTL = 1 hora.** Uma hora sem atividade encerra a sessao. `ACCESS_TTL` (10 min) e
   `SESSION_TTL` (30 dias) nao mudam.
2. **Janela deslizante enquanto ativo.** Cada refresh (disparado quando o token de acesso expira
   durante o uso) move o `idle_expires_at` para agora + 1 h. Quem esta usando nao e deslogado.
3. **Autoridade no servidor.** `_session_usable` ja exige `idle_expires_at > now`, e o refresh
   recusa sessao com idle vencido (nao ressuscita); o proprio refresh token expira no `idle_expires_at`.
   Passada a hora sem nenhum request, a proxima chamada falha e o painel manda para o login.

## Consequencias

- Computador fechado, aba escondida ou maquina dormindo por 1 h => precisa logar de novo. O polling
  do painel so corre com a aba visivel, entao "fora do sistema" conta como inatividade.
- Uma tela sempre visivel e ativa (ex.: modo feira em um monitor) continua renovando e nao cai —
  comportamento desejado para um painel de parede durante a feira.
- Nenhuma mudanca de protocolo, identidade ou assinatura: so a duracao da janela de inatividade.
