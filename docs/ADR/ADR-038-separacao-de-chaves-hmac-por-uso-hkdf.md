# ADR-038: separacao de chaves HMAC por uso (HKDF)

Status: **rascunho proposto em 2026-11-07, aguardando aprovacao do Voide**. Implementa o item 7
("Chaves") do [ADR-016](ADR-016-approved-actions.md) e o item M3 das revisoes de seguranca
(2026-10-24 e 2026-11-07).

## Contexto

Uma unica chave (`ABUSE_CONTROL_HMAC_KEY`) serve hoje a quatro usos, cada um com um dominio
diferente embutido na entrada do HMAC:

| Uso | Entrada |
|---|---|
| Pseudonimizacao de limite de abuso | `pseudonymize("auth-abuse:<dim>", valor)` |
| Codigo de recuperacao de senha | `pseudonymize("password-reset-code", "<user>:<code>")` |
| Aprovacao de comando | `pseudonymize("device-command-approval", "<cmd>:<code>")` |
| PIN de acao | `pseudonymize("action-pin", "<user>:<pin>")` |

onde `pseudonymize(namespace, value)` = `HMAC-SHA256(key, f"{namespace}\x00{value}")`.

**Sejamos honestos sobre o risco.** Isto **nao e uma vulnerabilidade exploravel hoje**: o
separador `\x00` entre namespace e valor ja garante separacao de dominio criptografica (nenhuma
entrada de um uso colide com a de outro). O beneficio real do HKDF e **gestao de chaves**, nao
tapar um buraco:

1. **Material de chave independente por uso** -> da para **rotacionar** uma subchave sem afetar as
   outras.
2. **Raio de dano menor** se uma subchave for exposta por um canal lateral especifico daquele uso.
3. **Alinhamento com o desenho ja aprovado** (ADR-016 item 7), que previu exatamente isto.

## Decisao

1. **Derivar subchaves por uso via HKDF-SHA256** (RFC 5869) da master `ABUSE_CONTROL_HMAC_KEY`,
   com `info` distinto e versionado por uso: `aval/rate-limit/v1`, `aval/reset-code/v1`,
   `aval/approval-code/v1`, `aval/action-pin/v1` (e `aval/vault-label/v1` quando/se existir).
   `salt` fixo ou vazio; o dominio e a versao vao no `info`.
2. **Cada consumidor passa a usar a sua subchave.** `AbuseControlKey` ganha `derive(purpose)` e os
   `_mac()` de cada modulo usam a subchave do seu uso em vez da chave crua.
3. **Versao no `info` (`/v1`)** permite rotacao futura de um uso sem tocar os outros.

## A decisao central que preciso de voce: migracao / compatibilidade

Trocar a derivacao **invalida todos os MACs ja gravados** com o esquema atual. Impacto por uso:

- `action_pins.pin_mac` (duravel): **todo PIN para de validar** -> o dono teria que recriar o PIN.
- Aprovacao de comando (efemera, <= 5 min): aprovacoes pendentes quebram. Toleravel.
- Codigo de recuperacao (efemero): codigos pendentes quebram. Toleravel.
- Pseudonimos de limite de abuso: recomecam (so zera contadores; sem dano).

Opcoes:

- **(A) Versao por registro.** Guardar `key_version` junto de cada MAC duravel (`pin_mac`).
  Verifica com o esquema da versao gravada; re-grava em v2 no proximo uso bem-sucedido (ex.: PIN
  re-hasheado no proximo acerto). **Zero interrupcao** para o dono. Mais codigo.
- **(B) Flag day.** No deploy, invalida os PINs; o dono **recria o PIN uma vez**. Os efemeros se
  resolvem sozinhos. Simples; uma interrupcao pontual.
- **(C) So nos efemeros.** Aplicar HKDF a limite/codigos/aprovacao e deixar o PIN no esquema atual
  por ora. Zero migracao do duravel, mas reduz o beneficio.

**Recomendacao:** dado o estagio (pre-feira, um unico dono), **(B) flag-day** e o mais simples e
honesto — recriar o PIN uma vez. Se quiser zero interrupcao, **(A)**.

## Consequencias

- Material de chave independente por uso e rotacao por versao.
- **Nao corrige uma falha exploravel** (a separacao de dominio ja existe hoje); e endurecimento e
  alinhamento com o ADR-016.
- Custo = a migracao escolhida acima. A master continua uma so (`ABUSE_CONTROL_HMAC_KEY`); muda
  como as subchaves saem dela.

## Nao implementado neste rascunho

Apenas o desenho. A implementacao vira em PR proprio **depois do seu aval** e **da escolha da
estrategia de migracao**, com testes (cada subchave difere; um MAC de um uso nao valida em outro;
e, se for a opcao A, verificacao cruzada de versao).
