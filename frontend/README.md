# Bots Central V2 — Web

Cliente web React/TypeScript/Vite. A API é sempre same-origin (`/api/v1`), sem proxy
de desenvolvimento, CORS ou credenciais embutidas.

## Desenvolvimento

```sh
npm install
npm run dev
```

O runtime sempre usa a API HTTP real. Login e refresh obtêm um access token opaco que
fica exclusivamente em memória; o refresh permanece no cookie `HttpOnly` do backend.
Nenhum token é gravado em `localStorage` ou `sessionStorage`.

Execute o frontend atrás da mesma origem do backend. Como CORS é desabilitado, o servidor
Vite isolado não é um substituto para essa topologia de desenvolvimento.

```sh
npm run lint
npm test
npm run build
```
