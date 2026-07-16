# Build the React app, then serve it with nginx (which also proxies /api).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# templates/ (not conf.d/) so the entrypoint runs envsubst over it at startup.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV MAX_UPLOAD_MB=25
EXPOSE 80
