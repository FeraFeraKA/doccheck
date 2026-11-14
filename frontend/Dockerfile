FROM node:26.12.1-bookworm-slim@sha256:88e480776c6149ff1d098cd304f44bf18057fb5d284a3329b78162d29821e28c AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npm install --global "pnpm@$(node -p 'require("./package.json").packageManager.split("@")[1]')" \
    && pnpm install --frozen-lockfile
COPY frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
COPY frontend/public/fonts/inter-OFL.txt ./public/fonts/
COPY frontend/public/demo ./public/demo
COPY contracts/check-result.v1.synthetic.json ../contracts/
COPY docs/synthetic/nrt-89/inputs.json ../docs/synthetic/nrt-89/
RUN pnpm build

FROM nginx:1.30.6-alpine@sha256:583b7f2fce1cdb8da5ad5c39ebd3c33b98b87d493190e548bdee1fa8c619c311
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
