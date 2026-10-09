FROM node:24-bookworm-slim
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages ./packages
RUN pnpm install --frozen-lockfile
COPY apps/web ./apps/web
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN pnpm --filter @factory/web build
EXPOSE 3000
CMD ["pnpm", "--filter", "@factory/web", "start"]
