# Multi-stage Dockerfile for ADCS Admin UI (Next.js standalone)
# Build: docker build --platform linux/amd64 -t adcs-admin-ui .

# ---------------------------------------------------------------------------
# Stage 1: Install dependencies
# ---------------------------------------------------------------------------
FROM node:25-alpine AS deps
WORKDIR /app
# The lockfile must be copied, and the install must be `npm ci`: it installs
# exactly the locked dependency tree, so the image ships what was tested
# (`npm install --frozen-lockfile` is not an npm option and would re-resolve).
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------------------
# Stage 2: Build the Next.js app (standalone output)
# ---------------------------------------------------------------------------
FROM node:25-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_ADCS_ADMIN_API_BASE=http://localhost:8080
ENV NEXT_PUBLIC_ADCS_ADMIN_API_BASE=${NEXT_PUBLIC_ADCS_ADMIN_API_BASE}

RUN npm run build

# License texts of the production npm dependencies, redistributed with the image.
RUN node scripts/third-party-notices.mjs > THIRD_PARTY_NOTICES.txt

# ---------------------------------------------------------------------------
# Stage 3: Production runtime (standalone — no node_modules needed)
# ---------------------------------------------------------------------------
FROM node:25-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder /app/THIRD_PARTY_NOTICES.txt ./licenses/THIRD_PARTY_NOTICES.txt
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
