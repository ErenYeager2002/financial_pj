# ============================================
# Stage 1: Install dependencies
# ============================================

ARG NODE_VERSION=docker.m.daocloud.io/library/node:22-slim

FROM ${NODE_VERSION} AS dependencies

WORKDIR /app

ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com

# Copy package-related files to leverage Docker cache
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# Install dependencies with frozen lockfile for reproducible builds
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    corepack enable \
    && corepack prepare pnpm@10.15.1 --activate \
    && pnpm config set registry https://registry.npmmirror.com \
    && pnpm install --frozen-lockfile

# ============================================
# Stage 2: Build the Next.js application
# ============================================

FROM ${NODE_VERSION} AS builder

WORKDIR /app

ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Build-time env vars — override these with --build-arg or in compose.yml
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ARG NEXT_PUBLIC_CLERK_SIGN_IN_URL=/auth/sign-in
ARG NEXT_PUBLIC_CLERK_SIGN_UP_URL=/auth/sign-up
ARG NEXT_PUBLIC_SENTRY_DISABLED=true
ARG NEXT_PUBLIC_APP_URL=http://localhost:3000

ENV BUILD_STANDALONE=true

RUN corepack enable \
    && corepack prepare pnpm@10.15.1 --activate \
    && pnpm build

# ============================================
# Stage 3: Production runner
# ============================================

FROM ${NODE_VERSION} AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV NEXT_TELEMETRY_DISABLED=1

# Copy public assets
COPY --from=builder --chown=node:node /app/public ./public

# Create .next dir with correct permissions for prerender cache
RUN mkdir .next && chown node:node .next

# Copy standalone output and static files
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# Run as non-root user
USER node

EXPOSE 3000

CMD ["node", "server.js"]
