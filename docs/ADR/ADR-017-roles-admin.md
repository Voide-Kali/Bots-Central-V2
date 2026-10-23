# ADR-017: Papéis "usuário" e "administrador"

Status: **aprovado pelo Voide em 21/10/2026** (pedido explícito: "funções que só o administrador
consegue ver… eu conserto o sistema pelo navegador"). Afeta autorização.

## Contexto

O usuário comum usa o Aval pelo Telegram e pelo painel: os computadores dele, as ações com PIN e
o histórico dele. O Voide também administra o servidor. Quando alguém pede ajuda, ele precisa
ver a saúde do sistema, contas travadas e pedidos com falha **sem abrir o banco com SQL**, como
precisou fazer em 21/10.

## Decisão

1. A tabela `users` ganha a coluna `role` ∈ {`user`, `admin`}, com padrão `user`.
2. **Ninguém vira administrador pela web.** A promoção só acontece com um comando no servidor:
   ```bash
   docker compose exec backend python -m app.admin promote email@exemplo.com
   ```
   Um invasor com acesso ao painel não consegue se promover.
3. As rotas `/api/v1/admin/*` exigem `role = admin` e têm **o mesmo formato de erro** de uma
   rota inexistente: não revelam que a área existe.
4. **O que o administrador vê:**
   - saúde: banco, bot, Gmail, IA e agentes online;
   - contagens de usuários, computadores e comandos por estado;
   - lista de usuários com e-mail, status e data;
   - pedidos com falha (tipo de ação, erro e data);
   - histórico de todos.
5. **O que o administrador faz:** ativar uma conta pendente, que é o reparo de 21/10. Essa ação
   fica auditada como `admin.user_activated`.
6. **O que o administrador nunca vê:**
   - conteúdo de arquivos ou fotos;
   - PINs e senhas (nem como hash);
   - telemetria detalhada de computadores de outras pessoas.

   O administrador também **não executa ações** nos computadores dos usuários.
7. O painel mostra a aba **Admin** só quando `/api/v1/auth/me` responde `role: "admin"`. A aba é
   só conveniência: quem decide o acesso é o backend.
8. Logs de containers ficam fora desta versão. O backend não tem acesso ao Docker, e dar esse
   acesso a ele seria um risco maior que o ganho. Para isso continua valendo o `doctor.sh` e o
   `docker compose logs` no servidor.

## Consequências

- Uma conta de administrador roubada vê a lista de e-mails dos usuários. Mitigações: PIN e
  senha longos, sessão curta e acesso só pela rede Tailscale.
- Cada ação de administrador fica no histórico append-only.
