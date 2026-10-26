# ADR-030: Exposicao publica do sistema inteiro (risco aceito, pre-feira)

Status: **aceito em 2026-10-26**. Decisao do Voide: deixar o Aval acessivel pela internet sem
exigir Tailscale em cada dispositivo. Reverte, por ora, a recusa do ADR-027 (que mantinha so
`/baixar` publico). O Voide aceita o risco explicitamente para esta fase.

## Contexto

Ate aqui o servidor so era alcancavel pela tailnet (SECURITY_MODEL, principio 5), e so `/baixar`
era publico (ADR-027). Isso obriga cada dispositivo gerenciado a ter Tailscale para parear e mandar
heartbeat. O Voide quer remover esse atrito: baixar e usar de qualquer notebook, sem configurar
Tailscale toda vez.

## Decisao

Expor o painel e a API inteiros pela internet, via Tailscale Funnel, no mesmo hostname `.ts.net`.

1. **Entrada publica por Funnel.** O Caddy ganha um listener HTTP interno (`:8080`), publicado so
   em `127.0.0.1:8082` no host. `sudo tailscale funnel --https=443 http://127.0.0.1:8082` publica
   todo o painel/API. Sem esse comando, nada fica exposto (a porta 127.0.0.1 sozinha nao expoe).
   A entrada da tailnet (HTTPS com o certificado `.ts.net`) continua sempre ligada.
2. **Mesmo hostname.** O Funnel serve no mesmo `aval.tail5e5757.ts.net`, entao o `Origin` bate com
   `PUBLIC_ORIGIN` e os cookies `Secure`/`SameSite=strict` e as checagens de CSRF seguem valendo.

## Risco aceito

A superficie publica passa a incluir login, API e o controle dos computadores. Qualquer pessoa na
internet pode tentar login, forca bruta, sondagem de falhas ou DoS. E o oposto do "menor exposicao"
do ADR-027. Aceito **por ora** (fase pre-feira), por decisao do dono, e **reversivel a qualquer
momento**: `sudo tailscale funnel --https=443 off` fecha o acesso publico e volta ao tailnet-only.

## Reforcos aplicados (o "portao")

- **IP real do cliente atras do Funnel — REVERTIDO (26/10).** A tentativa de propagar o IP real
  (`trusted_proxies` + `header_up X-Forwarded-For`) quebrou o login E os heartbeats dos agentes:
  o backend tem um parser estrito de X-Forwarded-For (`client_network`) que aceita **um unico IP,
  sem virgula**; ao confiar no proxy do Funnel e repassar o XFF, o backend passou a receber valor
  invalido/ambiguo e retornava **503** em todo login e heartbeat (um agente apareceu offline numa
  apresentacao). Revertido para o comportamento original: o Caddy ignora o XFF do cliente e manda
  **exatamente um IP** (o peer imediato) — testado para tailnet e Funnel. Consequencia aceita:
  atras do Funnel o cliente aparece como o proxy do Funnel, entao o limite **por IP** fica grosseiro
  ali; o limite **por conta** (e-mail) continua valendo e e a defesa principal do login. Reativar o
  IP real exige testar o XFF real do Funnel com cuidado (follow-up), nunca em cima de apresentacao.
- **HSTS com `includeSubDomains`.**
- **Defesas que ja existiam e seguem valendo:** senha Argon2id, sessoes no servidor, protocolo do
  agente assinado com anti-replay, acoes so com PIN, respostas genericas (sem enumeracao), `/docs`
  e `openapi` desligados em producao.
- **fail2ban (opcional, host).** O Caddy grava um log de acesso com o IP real; `deploy/server/
  fail2ban/` traz um filtro e um jail prontos para banir no firewall IPs com muitos 401/429 nas
  rotas de auth. E passo de host, opcional; o sistema funciona sem ele.

## O que NAO muda

- Identidade de dispositivo, pareamento (ainda exige o codigo do painel), autorizacao, protocolo,
  auditoria. Baixar o instalador continua sem dar poder nenhum sem o codigo.
- O `db` segue isolado na rede interna; o Funnel aponta so para o Caddy do painel.

## Pendencia para quando passar a fase

Reavaliar: voltar para tailnet-only (ADR-027) ou, se o acesso publico continuar, adicionar um
limite de taxa por IP no proprio Caddy (plugin `caddy-ratelimit`, exige imagem custom) e revisar o
modelo de ameaca com o sistema de fato publico.
