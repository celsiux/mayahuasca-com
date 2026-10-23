# Mayahuasca website

This repository contains the approved static website in `dist/`. It is published to GitHub Pages from the `main` branch. The Cloudflare Worker `mayahuasca-site` is a separate preview and rollback deployment of the same files.

## Production publishing

1. Edit files in `dist/` and commit to `main`.
2. The `Deploy site` GitHub Actions workflow publishes `dist/` to GitHub Pages.
3. Check `/`, `/experiencia-3-dias-peru/`, `/llms.txt`, `/robots.txt`, and `/sitemap.xml` on the public domain after deployment.

Cloudflare is the DNS provider. Its API credential is stored in Infisical at `/infra/cloudflare` as `${CLOUDFLARE_API_TOKEN}`. Never place the credential in this repository or GitHub Actions secrets. To deploy the same static files to the Worker preview from an authorized VertixOS environment:

```sh
${VERTIXOS_REPO:-$HOME/vertixos}/scripts/vertix-infisical-run --path /infra/cloudflare -- npx wrangler deploy
```

The older ChatGPT Sites project is not part of this publishing path. Video files referenced by the homepage are served from the existing public R2 endpoint; `dist/` contains the page files and image assets.
