FROM node:24-alpine

WORKDIR /app
COPY package.json ./
COPY src ./src
COPY public ./public

EXPOSE 8080
CMD ["node", "/app/src/server.js"]
