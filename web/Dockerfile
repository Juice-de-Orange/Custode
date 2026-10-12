# Production web image (used from Phase 8 onward; dev runs `npm run dev` on host).
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# AGPL §13 source link in the footer; empty = the upstream repository (docs/operations.md).
ARG VITE_SOURCE_URL=""
RUN npm run build

# Static serving via Caddy (default Caddyfile serves /usr/share/caddy on :80).
FROM caddy:2-alpine
COPY --from=build /app/dist /usr/share/caddy
