FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
# Use npm ci for reproducible builds when lockfile exists; fallback to npm install
RUN if [ -f package-lock.json ]; then npm ci --legacy-peer-deps --no-audit; else npm install --legacy-peer-deps --no-audit; fi

COPY . .

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
