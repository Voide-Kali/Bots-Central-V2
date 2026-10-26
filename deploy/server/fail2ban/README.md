# fail2ban para o Aval (opcional, ADR-030)

Reforco de host para quando o sistema esta exposto publicamente: bane no firewall os IPs que
acumulam tentativas de login falhas ou bloqueadas (HTTP 401/429) nas rotas de autenticacao. E
**opcional** — o sistema funciona sem ele; o limite de tentativas por conta/IP ja existe no app.

Pre-requisito: o `web` (Caddy) grava o log de acesso em `deploy/server/logs/access.log` (volume ja
incluso no compose), com o IP real do cliente (`client_ip`, atras do Funnel).

Instalar (no servidor, uma vez):

```
sudo apt-get install -y fail2ban
sudo cp deploy/server/fail2ban/filter.d/caddy-aval.conf /etc/fail2ban/filter.d/
sudo cp deploy/server/fail2ban/jail.d/caddy-aval.local /etc/fail2ban/jail.d/
sudo sed -i "s#/CHANGE/ME/aval#$HOME/aval#" /etc/fail2ban/jail.d/caddy-aval.local   # ajuste o caminho
sudo systemctl enable --now fail2ban
sudo systemctl restart fail2ban
```

Conferir:

```
sudo fail2ban-client status caddy-aval
```

Se `fail2ban` nao detectar a data das linhas (log vazio de "bans"), descomente a linha
`datepattern` em `/etc/fail2ban/filter.d/caddy-aval.conf` e reinicie o fail2ban. Ajuste
`maxretry`/`findtime`/`bantime` no jail ao seu gosto.
