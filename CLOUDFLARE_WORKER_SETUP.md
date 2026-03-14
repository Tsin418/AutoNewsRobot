# Cloudflare Worker Deployment (GitHub-linked)

This repo includes a Worker that triggers a GitHub Actions workflow on schedule.
It is used because Selenium-based Python crawling cannot run inside Cloudflare Workers runtime.

## 1) Install prerequisites
- Install Node.js LTS
- Install Wrangler: `npm install -g wrangler`

## 2) Login Cloudflare
- `wrangler login`

## 3) Configure Worker secret
Set GitHub PAT with workflow permission:
- `wrangler secret put GITHUB_TOKEN`

The token needs permissions:
- `repo`
- `workflow`

## 4) Confirm workflow target
Check values in `wrangler.toml`:
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_ID`
- `GH_WORKFLOW_REF`

## 5) Deploy
- `wrangler deploy`

## 6) Verify
- Open `<worker-url>/health` and expect `ok`
- Check GitHub Actions tab for dispatched workflow runs

## Optional: run without waiting for cron
- Call root URL to dispatch manually.
