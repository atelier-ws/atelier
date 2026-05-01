FROM node:20-slim

RUN apt-get update && apt-get install -y rsync && rm -rf /var/lib/apt/lists/*

WORKDIR /app/

# Install Docusaurus globally
RUN npm install -g create-docusaurus@latest

# Create Docusaurus project (classic template, TypeScript, no git)
RUN npx create-docusaurus@latest docs-site classic --typescript --git-strategy copy && \
    cd /app/docs-site && npm install

# Copy sync script
COPY docs-site/sync-docs.sh /app/docs-site/sync-docs.sh
RUN chmod +x /app/docs-site/sync-docs.sh

# Copy custom homepage, styles, config, sidebars, and logos
COPY docs-site/docusaurus.config.ts /app/docs-site/docusaurus.config.ts
COPY docs-site/sidebars.ts /app/docs-site/sidebars.ts
COPY docs-site/custom.css /app/docs-site/src/css/custom.css
COPY docs-site/index.tsx /app/docs-site/src/pages/index.tsx
COPY docs-site/favicon.svg /app/docs-site/static/img/favicon.svg
COPY docs-site/atelier-logo.svg /app/docs-site/static/img/atelier-logo.svg

# Copy Atelier docs into Docusaurus
COPY docs/ /app/docs-site/docs/

WORKDIR /app/docs-site/

EXPOSE 3200

CMD ["./sync-docs.sh"]
