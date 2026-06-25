# NEXT_PUBLIC_API_BASE_URL is baked in at *build* time (Next.js inlines NEXT_PUBLIC_*
# vars into the client bundle) -- it must be the address the *browser* will use to reach
# the API (your VPS's public IP/domain + port), not an internal Docker hostname like
# "http://api:8000", since that's only resolvable inside the Docker network.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "run", "start"]
