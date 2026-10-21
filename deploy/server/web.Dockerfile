# Builds the React panel and serves it with Caddy.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
