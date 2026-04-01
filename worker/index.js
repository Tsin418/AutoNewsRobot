/**
 * Cloudflare Worker scheduler that triggers a GitHub Actions workflow.
 *
 * Why this design:
 * - Cloudflare Workers cannot run Selenium/undetected_chromedriver directly.
 * - Worker acts as a reliable cron trigger and links to GitHub execution.
 */

async function dispatchGithubWorkflow(env, reason) {
  const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW_ID}/dispatches`;
  const payload = {
    ref: env.GH_WORKFLOW_REF || "master",
    inputs: {
      trigger_reason: reason,
      trigger_time: new Date().toISOString(),
    },
  };

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "autonewsrobot-worker",
    },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub dispatch failed: ${resp.status} ${body}`);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return new Response("ok", { status: 200 });
    }

    try {
      await dispatchGithubWorkflow(env, "manual_http");
      return new Response("workflow dispatched", { status: 200 });
    } catch (err) {
      return new Response(String(err), { status: 500 });
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchGithubWorkflow(env, "cron"));
  },
};
