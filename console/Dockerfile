# Multi-stage build
# Stage 1: Install deps and build
FROM node:20-alpine AS builder
WORKDIR /app

# Copy console package files
COPY packages/console/package.json packages/console/package-lock.json* ./
RUN npm ci

# Copy console source
COPY packages/console/ .

# Copy server shared types (used via @elydora/shared path alias)
COPY packages/server/src/shared ../server/src/shared

ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8787
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

# Stage 2: Production
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
