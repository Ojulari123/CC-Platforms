# Build context is the REPO ROOT (see docker-compose.yml), not services/forge/frontend,
# because nuxt.config.ts does `extends: ["../../../packages/ui"]` — the shared Nuxt layer
# lives outside this directory, so a context rooted here could not see it and the build
# would fail at config load. The paths below keep the repo's own layout inside the image.
FROM node:22.19-alpine AS build

WORKDIR /repo

# The shared layer first, in its own cached layer — it changes far less often than a page.
COPY packages/ui ./packages/ui

# Lockfile before source, so editing a component doesn't re-run npm ci.
COPY services/forge/frontend/package.json services/forge/frontend/package-lock.json ./services/forge/frontend/
WORKDIR /repo/services/forge/frontend
# --ignore-scripts skips the `nuxt prepare` postinstall, which would fail here: the app
# source isn't copied yet. `nuxt build` runs the same preparation itself a few lines down.
RUN npm ci --ignore-scripts

COPY services/forge/frontend ./
RUN npm run build

# Runtime carries only .output — no source, no node_modules, no build toolchain.
FROM node:22.19-alpine AS runtime

WORKDIR /app

COPY --from=build /repo/services/forge/frontend/.output ./.output

# Nitro reads HOST/PORT at boot. 0.0.0.0 because localhost inside a container is not
# reachable from the host. Port 3000 in every frontend image, like every backend image
# uses 8000; docker-compose.yml is what publishes it as :3001 on the host.
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
