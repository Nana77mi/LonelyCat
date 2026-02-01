FROM node:18-alpine

WORKDIR /app

COPY apps/web-console/package.json ./

RUN corepack enable && pnpm install

COPY apps/web-console/ ./

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]
