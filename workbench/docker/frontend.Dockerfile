# EE-free Evalith workbench frontend. Build context is the generated tree
# (workbench/.workbench/ee-free). No EE package or Rhesis brand asset is copied.
FROM mirror.gcr.io/library/node:24-alpine AS build

WORKDIR /app

COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci

COPY apps/frontend /app

ARG API_BASE_URL=http://backend:8080
ARG NEXTAUTH_SECRET=build-only
ENV API_BASE_URL=$API_BASE_URL \
    NEXTAUTH_SECRET=$NEXTAUTH_SECRET \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM mirror.gcr.io/library/node:24-alpine

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.mjs ./next.config.mjs
COPY --from=build /app/LICENSE /app/NOTICE /app/THIRD_PARTY_NOTICES.md /app/

RUN addgroup -S evalith && adduser -S evalith -G evalith && \
    chown -R evalith:evalith /app
USER evalith

EXPOSE 3000

CMD ["npx", "next", "start", "-p", "3000"]
