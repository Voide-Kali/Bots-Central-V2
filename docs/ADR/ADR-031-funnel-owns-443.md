# ADR-031: Funnel e o unico dono da porta 443 (corrige o conflito com o web)

Status: **aceito em 2026-10-31**. Correcao de um bug de desenho do ADR-030 que derrubou a stack.

## Problema

O ADR-030 pos o container `web` publicando `${TAILSCALE_IP}:443` (entrada HTTPS da tailnet) E, ao
mesmo tempo, ligou o Tailscale Funnel em `--https=443`. Os dois querem o **mesmo endereco:porta**
(`<tailnet-ip>:443`). Enquanto o container ja estava de pe, deu pra conviver de forma fragil; mas
ao recriar o `web` (`docker compose up -d`), o Docker nao conseguia mais bindar a 443 — o tailscaled
(Funnel) a segurava:

```
failed to bind host port <tailnet-ip>:443/tcp: address already in use
```

O `web` nao subia, e com ele caia o painel, a API e os heartbeats dos agentes (aparelhos offline).

## Decisao

O **Tailscale `serve`/`funnel` e o unico dono da :443**. O `web` serve **so HTTP simples** numa porta
de loopback; o tailscaled termina o TLS (com o certificado `*.ts.net`) e encaminha para la **tanto o
trafego da tailnet quanto o publico**.

1. **compose:** o `web` publica so `127.0.0.1:8082:8080` — removidas as binds `${TAILSCALE_IP}:443` e
   `:80`.
2. **Caddyfile:** removido o bloco `{$SERVER_HOSTNAME}` (que fazia auto-HTTPS na 443). Fica so o
   listener `:8080` (HTTP simples), que serve o painel, o `/baixar` e faz proxy do `/api` pro backend.
3. **No servidor:** `sudo tailscale funnel --bg --https=443 http://127.0.0.1:8082`. O Funnel ja inclui
   o `serve`, entao a tailnet E a internet chegam em `aval.<tailnet>.ts.net:443` -> 8082 -> web.

## Consequencias

- Acaba o conflito de porta: `docker compose up -d` recria o `web` sem erro.
- Tailnet e publico usam o mesmo caminho (tailscaled 443 -> 8082). O agente, que fala com
  `https://aval.<tailnet>.ts.net`, chega pelo `serve` do tailscaled.
- O `web` nao faz mais TLS (o tailscaled faz). O `Origin` continua `https://aval.<tailnet>.ts.net`
  (mesmo host), entao cookies `Secure`/`SameSite=strict` e CSRF seguem valendo.
- XFF: sem `trusted_proxies`/`header_up` (revertido no #82), o Caddy manda um unico IP limpo pro
  backend, entao `client_network` aceita — login e heartbeat funcionam. Por-IP fica grosseiro atras
  do Funnel; por-conta continua valendo (mesma analise do ADR-030, agora sem o bug).
- Reversivel para tailnet-only: `sudo tailscale funnel --https=443 off` + republicar `${TAILSCALE_IP}:443`
  no `web` (se um dia nao quiser acesso publico).

Validado com um caddy real: painel, `/baixar`, redirect, proxy de `/api` e fallback SPA, todos OK.
