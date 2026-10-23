# Mayahuasca website

This repository contains the approved static website in `dist/`. Cloudflare R2 bucket `maya-site` stores the page files and images; Worker `mayahuasca-site` serves them at the public URLs. The `main` branch is the deployment source.

## Publishing

1. Edit files in `dist/` and commit to `main`.
2. Deploy with Workers Builds when its GitHub connection is configured. Use `npm run deploy` from an authorized environment for a manual release. The command uploads `dist/` to R2 before deploying the Worker.
3. Check `/`, `/experiencia-3-dias-peru/`, `/llms.txt`, `/robots.txt`, and `/sitemap.xml` on the deployed hostname.

Cloudflare is the DNS and hosting provider. Its API credential is stored in Infisical at `/infra/cloudflare` as `${CLOUDFLARE_API_TOKEN}`. Never place the credential in this repository. To deploy from an authorized VertixOS environment:

```sh
${VERTIXOS_REPO:-$HOME/vertixos}/scripts/vertix-infisical-run --path /infra/cloudflare -- npm run deploy
```

The older ChatGPT Sites project is not part of this publishing path. `mayahuasca.com` and `www.mayahuasca.com` are attached directly to Worker `mayahuasca-site`. Video files referenced by the homepage are served from the separate Cloudflare R2 bucket `maya` through `media.mayahuasca.com`.

## Workers Builds connection

Connect `celsiux/mayahuasca-com` to the existing `mayahuasca-site` Worker in **Workers & Pages → mayahuasca-site → Settings → Builds**. Use the repository root, production branch `main`, no build command, and deploy command `npm run deploy`. Cloudflare requires an interactive authorization of its GitHub App before API setup. Its Builds API also requires a **user-scoped** API token with **Workers Builds Configuration: Edit** and **Workers Scripts: Read**; the existing account-scoped deployment token cannot configure Builds. Store any additional token in Infisical, never in this repository.

The root and `www` Worker custom domains are active. After each release, verify both hostnames return the expected homepage, offer page, images, and `llms.txt`.
