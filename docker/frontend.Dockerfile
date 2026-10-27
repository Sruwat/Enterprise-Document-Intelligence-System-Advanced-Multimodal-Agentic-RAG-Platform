FROM node:22-slim AS deps

WORKDIR /workspace/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

FROM node:22-slim AS builder

WORKDIR /workspace/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /workspace/frontend/node_modules ./node_modules
COPY frontend ./
RUN npm run build

FROM node:22-slim AS runner

WORKDIR /workspace/frontend
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

COPY --from=builder /workspace/frontend/.next/standalone ./
COPY --from=builder /workspace/frontend/.next/static ./.next/static
COPY --from=builder /workspace/frontend/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
