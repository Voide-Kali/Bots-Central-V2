# ADR-011: Telegram como interface conversacional e código por e-mail como fator de aprovação

Status: proposto (2026-10-21). O número 010 está reservado para o ADR do protocolo do agente
(JWS EdDSA), já aprovado e ainda não versionado.

## Contexto

O Marco 1 excluiu Telegram do escopo. A partir de agora o projeto precisa de uma interface
móvel antes de existir um app nativo: o app Flutter depende do Apple Developer Program
(push nativo e distribuição), fora do orçamento atual. O responsável quer uma experiência
intuitiva, sem depender do navegador no dia a dia, e uma demonstração para feiras de ciência.

## Decisão

1. **Telegram é a interface conversacional** desta fase: alertas, consultas e conversa com a
   IA de dispositivos. O bot roda no servidor do projeto (long polling; nenhuma porta aberta).
2. **Vínculo de conta por código de uso único**, gerado no painel autenticado e enviado ao bot.
   O bot ignora qualquer `chat_id` não vinculado. O token do bot fica só no ambiente do servidor.
3. **Níveis de risco:**
   - consulta (status, telemetria): sem confirmação;
   - baixo risco: botão de confirmação no Telegram;
   - alto risco (ex.: enviar arquivo, ações futuras de acesso remoto/instalação): **código de
     aprovação por e-mail**, digitado no Telegram.
4. **O código de aprovação é vinculado à ação**: o e-mail descreve exatamente a ação, o
   dispositivo e o solicitante; o código vale para essa ação, expira em 5 minutos, é de uso único
   e tem tentativas limitadas. Reaproveita os primitivos de material/HMAC da verificação de e-mail
   (ADR-008). O e-mail nunca contém link de aprovação.
5. **Conteúdo sensível não trafega pelo Telegram.** Arquivos marcados como sensíveis ou acima
   do limite do Bot API são entregues por link de download do próprio servidor, acessível só pela
   rede privada e com validade curta.
6. **Comandos de shell arbitrários continuam proibidos.** O bot só aciona ações tipadas do backend.
7. O fator de aprovação é **trocável**: no futuro, ações de maior risco podem exigir passkey
   (WebAuthn) sem mudar o restante do fluxo.

## Consequências

- Telegram e e-mail formam dois canais independentes: comprometer só um não aprova ações.
- Mensagens de bot não têm criptografia de ponta a ponta; o Telegram vê o conteúdo das conversas.
  Aceito para status/telemetria nesta fase; mitigado para arquivos pelo item 5.
- A verificação do código é feita pelo servidor: um servidor comprometido poderia aprovar ações.
  Aceito como risco desta fase (servidor sem portas públicas, acesso só por Tailscale); a
  mitigação futura é a aprovação assinada verificada no agente.
- Dependência de um serviço de terceiros (Telegram) para a interface; o app Flutter continua
  previsto (ADR-004) quando houver orçamento.
