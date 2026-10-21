# ADR-015: Primeira ação remota — enviar arquivo, aprovado por código de e-mail

Status: proposto (2026-10-21) — **exige aprovação explícita** (protocolo do agente + ação remota).

## Contexto

A tese do Aval é que nada acontece num computador sem o aval do dono. A primeira ação precisa
ser útil na demo e de baixo dano possível: trazer um arquivo do computador para o celular.

## Decisão

1. **Pedido** no Telegram: `/enviar NOME-DO-PC arquivo.pdf`. Só dispositivos **ativos do próprio
   usuário**; nome de arquivo **sem pastas** (sem `/`, `\`, `..`, nomes ocultos). No máximo 3
   pedidos abertos por usuário.
2. **Aprovação** (ADR-011): código de 8 dígitos enviado ao **e-mail verificado**, descrevendo a
   ação exata (arquivo, computador, destino). Vinculado ao comando por HMAC (`command_id:code`),
   vale **5 minutos**, no máximo **5 erros** (depois o pedido é negado). O usuário responde
   `/aprovar CÓDIGO` no Telegram. A IA (ADR-013) não tem caminho para pedir nem aprovar.
3. **Entrega ao agente:** depois de cada heartbeat aceito o agente faz
   `POST /devices/{id}/commands/next` com JWS EdDSA (`aud bots-central:commands:v1`) que
   **consome a mesma sequência anti-replay do heartbeat**. Só comandos `approved` são entregues.
4. **Execução no agente:** só `send_file`, só dentro de **uma pasta compartilhada** configurada
   (`shared_dir`; vazio = recurso desligado). `Lstat` + `O_NOFOLLOW` + `SameFile`: nada de
   symlink, pasta ou dispositivo; limite de 10 MB. Não existe shell.
5. **Resultado:** `POST /devices/{id}/commands/{cid}/result` com JWS
   (`aud bots-central:command-result:v1`, `cid`, `status`, `size`, `sha256`) e os bytes em
   `content_b64`. O servidor só aceita bytes cujo tamanho e SHA-256 batem com o que **a chave
   do dispositivo assinou**.
6. **Entrega ao dono:** o bot envia o arquivo ao chat que pediu e **apaga os bytes** do banco.
   Falha, expiração (10 min após aprovar) e bloqueio viram aviso no Telegram, uma vez.
7. Tudo auditado: `action.requested`, `approval_failed`, `approved`, `dispatched`,
   `completed`/`failed`, `delivered`.

## Consequências

- Um servidor comprometido ainda poderia criar e aprovar comandos (o código é verificado no
  servidor). Mitigação futura: aprovação assinada no celular e verificada pelo agente.
- O arquivo passa pelo Telegram (sem ponta a ponta). Para arquivos sensíveis, link de download
  pela rede privada fica como evolução.
- Latência de até ~30 s (o agente só pergunta após cada heartbeat).
