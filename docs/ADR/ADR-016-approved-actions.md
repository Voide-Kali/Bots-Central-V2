# ADR-016: Ações com aval: um modelo único para tudo que muda o computador

Status: **aprovado pelo Voide em 21/10/2026**, com o adendo abaixo. Afeta o protocolo do agente, a
autorização e a auditoria.

## Contexto

O inventário do sistema antigo (`docs/LEGACY-INVENTORY.md`) traz para o Aval quase todas as
funções do Kali Bunker. Ficou decidido em 21/10 que as funções que **mudam algo no computador**
só rodam com o aval do dono:

- bloquear e desbloquear a tela;
- foto da webcam;
- desligar, reiniciar e suspender;
- scan da rede local;
- banir e desbanir IP/MAC;
- ver e aplicar atualizações (`apt`);
- cofre de senhas (revelar e apagar).

O **terminal remoto** e qualquer ação **proposta pela IA** ficam de fora para sempre.

O Kali Bunker já tinha boas ideias que este ADR aproveita: a lista branca de ações com
parâmetros exatos (`action_policy.py`) e o digest canônico do que foi confirmado. O que faltava
nele era um segundo canal: a confirmação era feita no próprio chat do Telegram, e o próprio
`SECURITY.md` do Kali Bunker admitia que "não é segundo fator".

O ADR-015 já resolveu esse caminho para `send_file`. Este ADR **generaliza o mesmo caminho**, em
vez de inventar um caminho por ação.

## Decisão

### 1. Catálogo fechado de ações

Cada ação é uma entrada de um catálogo no código: um nome fixo, um esquema exato de parâmetros e
um texto de risco que aparece no e-mail. Nada fora do catálogo é aceito: nem texto livre, nem
comando, nem caminho arbitrário.

| Ação | Parâmetros (exatos) | Executa no agente |
|---|---|---|
| `lock_screen` | nenhum | `loginctl lock-sessions` / `pmset displaysleepnow` (Mac) |
| `unlock_screen` | nenhum | `loginctl unlock-sessions` (só Linux; no Mac não existe forma suportada e a ação fica indisponível) |
| `webcam_photo` | nenhum | uma foto com `fswebcam`/`imagesnap`, até 2 MB, devolvida como arquivo |
| `power` | `mode` ∈ {`shutdown`, `reboot`, `suspend`} | `systemctl poweroff/reboot/suspend` / `shutdown -h/-r now` (Mac) |
| `network_scan` | nenhum (a rede é a da rota padrão do PC) | `nmap -sn <rede>` com tempo máximo de 90 s |
| `ban` | `kind` ∈ {`ip`, `mac`}, `value` validado, `op` ∈ {`add`, `remove`} | regra `nft`/`iptables` numa chain própria `AVAL_BAN`. Nunca bane o IP do servidor, o gateway nem endereços do Tailscale |
| `apt_check` | nenhum | `apt list --upgradable` (só leitura, mas exige aval porque revela o sistema) |
| `apt_upgrade` | nenhum | `apt-get -y upgrade` (nunca `install` de nome livre) |
| `vault_reveal` / `vault_delete` | `label` (nome da entrada, validado) | cofre cifrado **no PC** (modelo do `voice_vault.py`: PBKDF2 + AES + HMAC). A senha mestra é digitada **no PC** na instalação, nunca no Telegram |

Cada agente declara na instalação quais ações aceita (`allowed_actions` no `config.json`, vazio
por padrão). Uma ação que o agente não declarou nunca é entregue a ele.

### 2. Pedido

O pedido vem só do menu do Telegram ou do painel, nunca da IA. O servidor:

1. valida o catálogo e os parâmetros;
2. confere que o computador é do dono e está ativo;
3. gera o **digest canônico**: SHA-256 de `{acao, parametros, device_id, user_id}` em JSON
   canônico;
4. grava um `DeviceCommand` como `pending_approval`, guardando o digest.

### 3. Aval por e-mail

Funciona como no ADR-015:

- um código de 8 dígitos vai para o e-mail verificado do dono;
- o e-mail diz, em português, **qual ação**, em **qual computador** e **qual o risco**;
- o código fica vinculado ao comando por HMAC, com chave própria para este uso (ver item 7);
- vale 5 minutos e aceita no máximo 5 erros;
- o dono aprova respondendo `/aprovar CÓDIGO`.

As ações `power` e `unlock_screen` trazem um aviso extra no e-mail.

### 4. Entrega e execução

O caminho é o mesmo do ADR-015: o agente busca o próximo comando com um JWS assinado, depois de
cada heartbeat, usando a mesma sequência anti-replay.

O comando entregue carrega a ação, os parâmetros e o digest. O agente:

1. recalcula o digest e recusa o comando se não bater;
2. confere `allowed_actions`;
3. executa **um programa fixo, com argumentos fixos**, sem shell;
4. aplica limite de tempo e de tamanho da saída.

### 5. Resultado

O resultado volta assinado, como no ADR-015:

- **texto curto**: scan, `apt_check`, `vault_reveal`;
- **arquivo**: a foto;
- **só status**: as outras ações.

`vault_reveal` volta como mensagem do Telegram que se apaga sozinha em 60 s.

### 6. Auditoria

Cada etapa fica no histórico append-only (`action.requested`, `approved`, `dispatched`,
`completed`/`failed`), incluindo o nome da ação e o digest. Nunca entram no histórico os
parâmetros sensíveis: a senha revelada e o rótulo do cofre.

### 7. Chaves

Este ADR inclui a separação das chaves HMAC por uso, derivadas por HKDF da chave atual:
`rate-limit`, `reset-code`, `approval-code` e `vault-label`. Hoje uma única chave serve a todos.

## Consequências

- **Um servidor comprometido ainda poderia criar e aprovar comandos**, porque o código é
  verificado no servidor. Os limites são o catálogo fechado e o `allowed_actions` no agente: o
  pior caso é o pior item que o dono habilitou naquele PC. A evolução futura é a aprovação
  assinada no celular e verificada pelo agente.
- **`unlock_screen` e `vault_reveal` são os itens de maior risco**, e foram aceitos pelo dono
  (21/10). Por isso ficam desligados por padrão no `allowed_actions`.
- **`apt_upgrade` pode quebrar o sistema.** Só no Linux, só com aval, e o resultado mostra o que
  foi atualizado.
- **Implementação em PRs separados**, na ordem: `lock_screen` → `webcam_photo` → `power` →
  `network_scan` → `ban` → `apt_*` → `vault_*`. Cada PR traz os testes de recusa (ação fora do
  catálogo, parâmetro extra, digest trocado, ação não declarada pelo agente).
- **Na pesquisa da feira**, isso vira mais uma hipótese testável: com a IA conectada ao catálogo
  só para leitura, nenhum ataque consegue disparar uma ação do catálogo.

## Adendo (21/10/2026): decisões do dono depois da aprovação

1. **Aprovação por PIN pessoal em vez de e-mail a cada ação.**
   - O código por e-mail fica só para criar a conta e redefinir a senha.
   - As ações são aprovadas com um **PIN de 6 dígitos**, criado no painel. Criar ou trocar o PIN
     exige a senha da conta.
   - O PIN é guardado como HMAC com a chave do servidor (tabela `action_pins`); PINs óbvios são
     recusados.
   - 5 erros travam as aprovações por 15 minutos.
   - O PIN aprova só o pedido mais recente; pedidos por PIN mais antigos expiram.
   - O bot apaga a mensagem do PIN.
   - Sem PIN configurado, o código por e-mail continua valendo.
   - Risco aceito: o PIN é digitado no mesmo celular do Telegram. Ele protege contra o celular
     desbloqueado ou roubado, não contra quem também sabe o PIN.
2. **Botões e frases.**
   - O cartão de cada computador tem botões para as ações.
   - Frases como "bloqueia o Mac" são reconhecidas por **padrões fixos sobre a mensagem do
     próprio dono** (`app/telegram/intents.py`), não pelo modelo de IA. A IA continua sem
     caminho para iniciar ações (ADR-013).
3. **Foto automática quando errarem a senha (próximo passo).** É um sensor opcional, ativado na
   instalação (`AVAL_SENSORS`), e equivale a um aval dado uma vez pelo dono. A foto vai só para o
   Telegram do dono. Começa pelo Linux.
4. **Papéis usuário/administrador.** Vão para o ADR-017.
