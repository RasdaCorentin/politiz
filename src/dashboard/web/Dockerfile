# Stage 1: build the static bundle. Node exists only here, never on the host or at runtime.
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY vite.config.js index.html ./
COPY public/ public/
COPY src/ src/
# Photos des candidats : seules les miniatures libres, téléchargées ici et servies par nginx
# (même origine). Le dépôt ne garde que leurs métadonnées ; un échec réseau laisse les initiales.
COPY images/candidats-images.json images/
COPY outils/telecharger_images.mjs outils/
RUN node outils/telecharger_images.mjs images/candidats-images.json public/images/candidats
RUN npm run build

# Stage 2: nginx serves the compiled files only (non-root).
FROM nginxinc/nginx-unprivileged:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080
