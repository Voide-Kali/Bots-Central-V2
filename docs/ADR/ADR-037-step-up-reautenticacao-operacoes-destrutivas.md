# ADR-037: step-up (reautenticacao recente) para operacoes destrutivas de dispositivo

Status: **rascunho proposto em 2026-11-07, aguardando aprovacao do Voide**. Implementa a primeira
fatia concreta do [ADR-007](ADR-007-reauthentication-security-gate.md), que esta marcado como
"implementacao pendente". Motivado pelo achado H1 da revisao de seguranca de 2026-11-07
(`claude/revisao-seguranca-2026-11-07.md`).

## Contexto

Hoje as operacoes de ciclo de vida de um dispositivo sao autorizadas **apenas pelo bearer de
sessao** (`_device_principal` -> `authenticate_access`), sem passo adicional:

- `forget` (`DELETE /devices/{id}`): apaga o computador e toda a telemetria. **Irreversivel.**
- `rename` (`POST /devices/{id}/name`): troca o nome de exibicao. Reversivel.
- `approve` / `reject`: aprovam ou recusam um pareamento pendente. Baixo impacto.

O ADR-007 desenhou um Security Gate com prova recente (reautenticacao que expira em ate 5 min,
nao renovada por refresh), mas **nada disso foi implementado**. As colunas existem na tabela de
sessao desde a migracao `0002` (`recent_reauthenticated_at`, `recent_reauthentication_expires_at`,
`recent_reauthentication_context`) e **nunca sao lidas em lugar nenhum** do codigo.

Resultado: uma sessao roubada (mitigada, mas nao impossivel: CSP restritiva, token em header e
nao em cookie, sessao de 1 h) permite **apagar permanentemente** os dispositivos do dono sem
nenhuma prova adicional de que e o dono ali.

## Decisao (fatia minima, nao o Gate completo)

Entregar a menor peca util do ADR-007, sem construir o Policy Engine inteiro:

1. **Endpoint de reautenticacao.** `POST /auth/reauth` recebe a senha da conta, verifica com
   `verify_password` (Argon2), e grava na sessao atual `recent_reauthenticated_at = now`,
   `recent_reauthentication_expires_at = now + 5 min`, `recent_reauthentication_context` com o
   escopo. Refresh e `last_seen_at` **nao** renovam esse prazo (regra do ADR-007). Sujeito ao
   mesmo controle de abuso das demais rotas de senha.
2. **Exigir prova recente valida para `forget`.** Antes de apagar, o servidor verifica a janela
   de prova recente da sessao. Sem prova valida -> `401`/`403` com codigo estruturado
   (`reauth_required`) e o prazo; o painel pede a senha, chama `/auth/reauth` e repete o `forget`.
3. **Deny-by-default, verificado no servidor, expira em <= 5 min.** Step-up **nao** conserta
   falta de ownership: a checagem de dono (`_owned_device`, filtrando por `user_id`) continua
   valendo antes e independente disto.
4. **Auditoria.** Registrar `reauthentication_success` / `reauthentication_failure` e, quando o
   Gate nega, `security_gate_denial` (rotulos ja previstos no `AUTH.md`). Sem gravar a senha.

## Decisoes que preciso que voce feche (sao as perguntas do rascunho)

- **(a) Metodo do step-up.** Senha da conta (mais forte; coerente com "criar PIN exige a senha")
  ou o PIN de acao de 6 digitos que ja existe? **Recomendacao: senha da conta**, so para `forget`.
- **(b) Escopo.** So `forget`, ou tambem `rename`/`approve`/`reject`? **Recomendacao: so `forget`
  nesta fatia** — e o unico irreversivel; `rename` e reversivel e `approve`/`reject` sao de baixo
  impacto.
- **(c) Prazo.** 5 min (padrao do ADR-007). Confirmar.
- **(d) Superficie.** O step-up vale no **painel web**. No Telegram o `forget` **nao existe** e
  **nao sera adicionado** (acao destrutiva sem step-up fora do painel seria o oposto disto).
  Confirmar que `forget` fica so no painel.

## Consequencias

- Fecha a janela de "sessao roubada apaga tudo" para a acao mais destrutiva, com custo pequeno:
  um endpoint, um guard e a UX de pedir a senha no painel.
- **Reaproveita as colunas que ja existem** (migracao 0002): nenhuma migracao nova.
- E a primeira peca real do ADR-007; o Gate/Policy Engine versionado e completo continua trabalho
  futuro, fora deste ADR.
- Nao quebra nada existente: so adiciona uma exigencia a uma rota.

## Nao implementado neste rascunho

Apenas o desenho. A implementacao vira em PR proprio **depois do seu aval**, com testes de recusa
(sem prova recente -> 401; prova expirada -> 401; prova de outra sessao nao vale; dono errado
continua 404).
