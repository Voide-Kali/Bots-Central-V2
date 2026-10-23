# Site do Aval

Página de apresentação do projeto, estática e sem dependências: `index.html`, as telas em `img/`
(capturas do painel com dados de exemplo) e as fontes em `fonts/` (Bebas Neue e EB Garamond,
licença SIL OFL, auto-hospedadas para não depender do Google).

Ver localmente: `python3 -m http.server -d site 8080` e abrir http://localhost:8080.

A demonstração "Escreva um pedido" usa as mesmas regras fixas do bot
(`backend/app/telegram/intents.py`), reescritas em JavaScript só para mostrar; nada é enviado.
