# Bot do Telegram (v0.1)

Interface conversacional e alertas (ADR-011). O bot roda no servidor por *long polling*:
nenhuma porta precisa ser aberta.

## Configurar

1. No Telegram, fale com **@BotFather** → `/newbot` → escolha nome e usuário (termina em `bot`).
2. Guarde o token **só** no `.env` do servidor (nunca no Git nem em outra IA):
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_BOT_USERNAME=seu_bot
   ABUSE_CONTROL_HMAC_KEY=<python3 -c "import secrets;print(secrets.token_urlsafe(32))">
   ```
3. Suba o serviço: `docker compose --profile telegram up -d telegram`.

## Usar

1. No painel, card **Telegram** → **Vincular Telegram** → toque em **Abrir no Telegram**
   (ou envie `/vincular CODIGO` ao bot). O código vale 10 minutos e uma única vez.
2. Comandos: `/status`, `/desvincular`, `/ajuda`.
3. Alertas automáticos quando um dispositivo ativo fica offline ou volta (verificação a cada 30 s;
   offline = sem heartbeat aceito há 90 s).

## Perguntar para a IA (ADR-013)

Com `ASSISTANT_OLLAMA_URL` configurado, qualquer mensagem que não seja comando vira pergunta
para a IA local (ex.: “qual PC está mais quente?”, “quanto de disco sobra no Mac?”). Ela só
consulta: não executa nenhuma ação. Limite de 20 perguntas por chat a cada 10 minutos.

## Segurança

- Só chats **privados**; o bot ignora grupos, outros bots e mensagens em que remetente ≠ chat.
- Chat sem vínculo só recebe instruções de vínculo — nunca dados.
- Vínculo checa também o `telegram_user_id`; um chat já ligado a outra conta não pode ser tomado.
- Tentativas de vínculo limitadas (5 por chat a cada 10 min, 200 global), *fail-closed*.
- Só o digest SHA-256 do código é guardado; código novo invalida o anterior.
- Mensagens em texto puro (sem Markdown/HTML) porque nomes de dispositivos vêm dos agentes.
- O token faz parte da URL da API; erros nunca registram a URL nem a exceção original.
- O Telegram vê o conteúdo das mensagens (bots não têm ponta a ponta): só status e telemetria
  passam por aqui; arquivos sensíveis terão outro caminho (ADR-011, item 5).
