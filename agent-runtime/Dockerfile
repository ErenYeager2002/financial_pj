ARG NODE_VERSION=docker.m.daocloud.io/library/node:22-slim

FROM ${NODE_VERSION} AS builder
WORKDIR /app/agent-runtime
ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com
COPY agent-runtime/package.json agent-runtime/pnpm-lock.yaml agent-runtime/tsconfig.json ./
COPY agent-runtime/src ./src
RUN corepack enable \
    && corepack prepare pnpm@10.15.1 --activate \
    && pnpm config set registry https://registry.npmmirror.com \
    && pnpm install --frozen-lockfile --ignore-scripts \
    && pnpm run build \
    && pnpm prune --prod

FROM ${NODE_VERSION} AS runner
WORKDIR /app/agent-runtime
ENV NODE_ENV=production
COPY --from=builder --chown=node:node /app/agent-runtime/package.json ./package.json
COPY --from=builder --chown=node:node /app/agent-runtime/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/agent-runtime/dist ./dist
USER node
CMD ["node", "dist/workflow-harness-worker.js"]
