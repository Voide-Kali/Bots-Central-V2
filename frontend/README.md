# Bots Central V2 Web

The MVP-1 web client uses React, TypeScript and Vite. It provides account flows and Device Center. Runtime API calls are same-origin under `/api/v1`; access tokens stay in memory and refresh uses the backend `HttpOnly` cookie. No token is stored in `localStorage` or `sessionStorage`.

## Development

Use a Node/npm version compatible with the committed lockfile, then run:

```bash
npm ci
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
```

A standalone Vite server is not the functional browser topology because backend CORS is intentionally disabled. For MVP-1 local operation, run Vite on loopback behind the versioned Caddy harness in [LOCAL_E2E](../docs/LOCAL_E2E.md). Do not add a client-side API token, CORS workaround or persistent token storage.
