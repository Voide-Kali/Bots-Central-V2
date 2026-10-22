# ADR-019: Foto automática quando alguém erra a senha do computador

Status: **proposto em 22/10/2026**. O pedido é do Voide, de 21/10: "quando a senha estiver
incorreta, ele vai tirar a foto automaticamente". A proposta muda o protocolo do agente, porque
o agente passa a mandar um evento por conta própria.

## Contexto

Todas as ações do Aval até agora seguem o ADR-016: o dono pede, aprova com o PIN e só então o
agente age. Este sensor é diferente. Quem dispara é o próprio computador, quando alguém erra a
senha. O resultado é uma foto que vai só para o dono. Nada muda no computador e nenhuma ordem
vem do servidor.

## Decisão

1. **Opcional e desligado por padrão.** O sensor só funciona se o dono ligar na instalação:
   `AVAL_SENSORS=failed_login_photo`. Ele também precisa da câmera, que o instalador libera
   como já faz para a ação `webcam_photo`.
2. **Detecção no Linux.** O agente lê o diário do sistema com o programa fixo
   `journalctl -f -n 0 -o json`, sem shell e com argumentos fixos. Para isso o instalador põe o
   usuário do agente no grupo `systemd-journal`. Uma falha conta quando a mensagem é uma falha
   de autenticação do PAM ou do sshd e vem de um destes programas: tela de login ou de bloqueio
   (gdm, lightdm, sddm e os bloqueadores de tela), `login`, `sudo`, `su`, `sshd` ou `polkit`.
   O texto do diário nunca sai do computador. Só vai o nome do programa (por exemplo,
   `gdm-password`).
3. **No máximo uma foto por minuto.** Isso vale no agente e também no servidor, que aceita no
   máximo 5 eventos a cada 10 minutos por computador.
4. **Envio assinado.** O envio vai para `POST /api/v1/devices/{id}/events`, com um JWS de
   audiência própria (`bots-central:event:v1`) e a mesma sequência anti-replay. Os campos
   assinados são o tipo (`failed_login`), o programa, o tamanho e o SHA-256 da foto. A foto vai
   ao lado, com até 5 MB.
5. **Entrega.** O bot manda a foto ao chat do dono com a legenda "Senha errada no tropa (tela
   de login), 22/10 10:31". A foto é apagada do banco assim que é entregue, ou depois de 24 h.
6. **Auditoria.** O evento `sensor.failed_login` registra o computador e o programa. A foto
   nunca vai para a auditoria.
7. **Sem foto.** Se a câmera falhar, o evento chega sem foto e o dono recebe só o aviso de
   senha errada.

## Consequências

- O dono descobre na hora quando alguém tenta entrar no computador dele.
- Um agente comprometido pode mandar fotos falsas para o dono, mas só para o dono, com o limite
  acima e com o mesmo nível de confiança que já existe na telemetria.
- macOS fica para depois: lá a falha de senha só aparece no `log stream`, com permissões
  diferentes.
- A pessoa fotografada é quem estava na frente da câmera do computador do próprio dono. O
  painel e o instalador precisam deixar claro que o sensor existe.
