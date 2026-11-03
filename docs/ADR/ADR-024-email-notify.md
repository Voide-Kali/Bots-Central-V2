# ADR-024: Aviso e resumo de e-mails novos (leitura)

Status: **proposto em 23/10/2026**. Pedido do Voide (23/10): comecar o gerenciamento de e-mails.
Primeiro passo: avisar e-mails novos no Telegram, com um resumo curto feito pela IA local. E
LEITURA pura; a IA nunca responde, apaga nem envia e-mail.

## Contexto

O inventario do Kali-Bunker (secao 2.6) marca "monitorar contas e avisar no Telegram, com resumo
por IA local, guardando so o ID opaco, nunca o conteudo" como servico proprio, depois da feira. O
Voide quer comecar agora. Este ADR traz so o nucleo seguro e testavel; a conexao real com o Gmail
depende de credenciais OAuth que o Voide configura (nao entram no codigo).

## Decisao

1. **Leitura, nunca acao.** O subsistema so LE a caixa e avisa. Nao responde, nao marca, nao apaga,
   nao envia. A IA (Ollama local) so resume; nao tem ferramentas (mesmo principio do ADR-013/023).
2. **Guardar so o ID opaco, nunca o conteudo.** Uma tabela `email_seen` guarda apenas o id opaco da
   mensagem (por conta, por dono) e a data, para nao avisar duas vezes. Assunto, remetente e corpo
   NUNCA sao gravados no banco; passam so em memoria, do provedor para o aviso do Telegram.
3. **Resumo pela IA local.** O resumo e feito pelo Ollama no proprio servidor; o conteudo do e-mail
   nao sai da maquina. O prompt trata o e-mail como dado, nunca instrucao (defesa de injection), e
   a IA e instruida a nao agir.
4. **Provedor por interface.** `MailProvider` e uma interface (`fetch_recent`). A implementacao
   real do Gmail (OAuth, API) e um passo seguinte e exige o cliente OAuth que o Voide cria no Google
   (client id/secret), guardado so no `.env` do servidor. O nucleo e testado com um provedor falso.
5. **Entrega pelo bot.** Uma passada no loop do bot (como a de eventos/arquivos) pega os e-mails
   novos, monta o aviso ("Novo e-mail de X: <assunto>" + resumo curto) e manda ao chat do dono.
   Limites de tamanho e de quantidade por passada, sem spam.
6. **Opcional e desligado por padrao.** So liga quando o Voide configurar uma conta e as credenciais.
   Sem conta configurada, o subsistema nao faz nada.

## Consequencias

- O dono fica sabendo de e-mails novos sem abrir a caixa, com um resumo, e o conteudo nunca e
  gravado nem sai do servidor.
- A superficie nova e de LEITURA de uma conta externa: o risco e de privacidade (um e-mail lido),
  mitigado por nao gravar conteudo, resumo local e a IA sem acao. Nenhum poder sobre o computador.
- OAuth do Gmail fica para o proximo passo, dependente das credenciais do Voide. Ate la, o nucleo
  existe e e testado, mas nao conecta em conta real.
- Responder/arquivar/apagar e-mail NAO entra: seria dar acao a IA, contra o principio do Aval.

## Implementacao (Gmail API, leitura) — 23/10/2026

O "proximo passo" do item 4 foi implementado reaproveitando o cliente de Gmail do antigo
Kali-Bunker, agora como provedor que obedece a interface `MailProvider`:

- `app/inbox/gmail_api.py`: `GmailApiProvider` (OAuth2, escopo `gmail.readonly`). So LE: lista os
  nao-lidos do INBOX e extrai cabecalhos e um trecho de texto, em memoria. Nunca envia, apaga nem
  marca. Reusa o `token.json` ja autorizado no Google (o mesmo do Kali-Bunker); credenciais ficam
  so no `.env`/arquivo montado, nunca no codigo. Falha de rede nao derruba o loop do bot.
- `EmailFilter` (em `inbox.py`): filtros de remetente/dominio/assunto (noreply, newsletter, promo),
  iguais aos do Kali-Bunker. E-mail filtrado e gravado como visto (nao reavalia), mas nao vira aviso.
- Resumo pela IA LOCAL (Ollama), nunca na nuvem — o conteudo do e-mail nao sai da maquina.
- Ligado no loop do bot por `_email_watch`/`_deliver_emails`, numa passada propria a cada 60s.
- Opcional e desligado por padrao: so liga com `GMAIL_TOKEN_FILE`, `GMAIL_ACCOUNT` e `EMAIL_OWNER`
  no `.env`. As libs do Google entram na imagem so com `INSTALL_GMAIL=1` (imagem enxuta por padrao).

O escopo `gmail.readonly` e a ausencia de ferramentas na IA mantem a garantia: no maximo um aviso
errado, nunca uma acao. IMAP tambem continua disponivel como provedor alternativo.

## Garantia de escopo somente leitura (reforco, 26/10/2026)

O ADR exige `gmail.readonly`, mas reaproveitar um `token.json` antigo poderia trazer um escopo mais
amplo (`gmail.modify`, `gmail.send`, `mail.google.com`) sem que ninguem percebesse — um token
capaz de enviar/apagar guardado no servidor, exatamente o risco que o ADR quer eliminar. Reforcos:

- **O backend recusa, no ar, qualquer token que nao seja somente `gmail.readonly`.** `build_service`
  (gmail_api.py) le os escopos gravados no `token.json` e chama `assert_read_only` antes de montar
  qualquer cliente; escopo extra, ou ausencia de escopo registrado, derruba a ativacao com uma
  mensagem clara (e o loop do bot segue, so sem e-mail). Garantia por construcao, nao por confianca.
- **`deploy/release/verificar-token-gmail.py`**: confere o token OFFLINE (so le o arquivo) e diz se
  e somente leitura, antes de montar no servidor.
- **`deploy/release/autorizar-gmail.py`**: refaz a autorizacao pedindo so `gmail.readonly`, para
  gerar um token novo quando o antigo nao for somente leitura (ou nao existir).
