FROM node:20-slim

RUN apt-get update && apt-get install -y rsync && rm -rf /var/lib/apt/lists/*

WORKDIR /app/

# Copy docs-site project (self-contained with package.json)
COPY docs-site/ /app/docs-site/

# Install dependencies
RUN cd /app/docs-site && npm ci

# Copy public-facing docs (from repo root, synced at build time)
COPY docs/ /app/docs/

WORKDIR /app/docs-site/

EXPOSE 3200

CMD ["./sync-docs.sh"]
