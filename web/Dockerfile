# Production web image (used from Phase 8 onward; dev runs `npm run dev` on host).
FROM node:26-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Static serving via Caddy (default Caddyfile serves /usr/share/caddy on :80).
FROM caddy:2-alpine
COPY --from=build /app/dist /usr/share/caddy
