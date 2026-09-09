# Bots Central V2 — Web

Cliente web React/TypeScript/Vite. A API é sempre same-origin (`/api/v1`), sem proxy
de desenvolvimento, CORS ou credenciais embutidas.

## Desenvolvimento

```sh
npm install
npm run dev
```

Por padrão, desenvolvimento usa `VITE_API_ADAPTER=mock` para permitir avaliação visual
antes do contrato de login/dispositivos. Para falar com a API same-origin, defina
`VITE_API_ADAPTER=http`. Builds de produção usam `http` como padrão.

O mock é somente uma demonstração de interface: não emite credenciais e não representa
uma sessão autorizada pelo servidor.

```sh
npm run lint
npm test
npm run build
```
