import { expect, Page, test } from "@playwright/test";

async function mockBase(page: Page) {
  await page.route("**/auth/login", async (route) => route.fulfill({ json: { user: { user_id: "u1", email: "founder@aiwana.local", display_name: "Aiwana Founder" }, session_token: "token" } }));
  await page.route("**/auth/signup", async (route) => route.fulfill({ json: { user: { user_id: "u1", email: "founder@aiwana.local", display_name: "Aiwana Founder" }, session_token: "token" } }));
  await page.route("**/auth/me", async (route) => route.fulfill({ json: { user_id: "u1", email: "founder@aiwana.local", display_name: "Aiwana Founder" } }));
  await page.route(/\/workspaces$/, async (route) => route.fulfill({ json: [{ workspace_id: "default", name: "Default Knowledge Space" }] }));
  await page.route("**/documents?**", async (route) => route.fulfill({ json: [{ document_id: "doc-1", filename: "contract.pdf", page_count: 4, status: "indexed" }] }));
  await page.route("**/readiness/launch", async (route) => {
    await route.fulfill({ json: { status: "ready", blocker_count: 0, warning_count: 0, summary: "Aiwana launch readiness checks passed.", checks: [] } });
  });
  await page.route("**/observability/workspaces/default/snapshot", async (route) => {
    await route.fulfill({
      json: {
        components: { worker: { status: "ready" }, huggingface: { enabled: false }, graph_eval: { lift: "n/a" } },
        retrieval: { cache_hit_rate: 0.42, blocked_answer_rate: 0.02 },
        latency: { p95_ms: 812 },
      },
    });
  });
  await page.route("**/workspaces/default/chat/sessions", async (route) => route.fulfill({ json: [] }));
  await page.route("**/workspaces/default/api-keys", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: { key_id: "key-1", name: "Workspace automation", masked_key: "ak_live_****", role: "viewer", permissions: ["workspace.read"], api_key: "ak_live_secret" } });
      return;
    }
    await route.fulfill({ json: [{ key_id: "key-1", name: "Workspace automation", masked_key: "ak_live_****", role: "viewer", permissions: ["workspace.read"], revoked_at: null }] });
  });
  await page.route("**/workspaces/default/api-keys/key-1", async (route) => route.fulfill({ status: 204 }));
}

async function clickNav(page: Page, name: RegExp, isMobile: boolean) {
  if (isMobile) await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name }).click();
}

async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByText("Log in to open your Aiwana workspace.")).toBeVisible();
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Grounded answers across contracts")).toBeVisible();
}

test("route-based shell navigates dashboard, chat, sources, evidence, admin, and settings", async ({ page, isMobile }) => {
  await mockBase(page);
  await login(page);
  await clickNav(page, /Chat/i, isMobile);
  await expect(page.getByText("Agentic chat")).toBeVisible();
  await clickNav(page, /Sources/i, isMobile);
  await expect(page.getByText("Upload center")).toBeVisible();
  await clickNav(page, /Evidence/i, isMobile);
  await expect(page.getByText("No answer selected yet")).toBeVisible();
  await clickNav(page, /Admin/i, isMobile);
  await expect(page.getByText("Observability")).toBeVisible();
  await clickNav(page, /Settings/i, isMobile);
  await expect(page.getByText("Account")).toBeVisible();
});

test("chat request streams tokens and stores evidence for the evidence route", async ({ page, isMobile }) => {
  await mockBase(page);
  await page.route("**/chat/sessions", async (route) => {
    if (route.request().url().includes("/workspaces/")) {
      await route.fulfill({ json: [] });
      return;
    }
    await route.fulfill({ json: { session_id: "session-1" } });
  });
  await page.route("**/chat/query/stream", async (route) => {
    const final = {
      answer: "The agreement has a termination risk. [Source: contract.pdf p.4]",
      confidence: 0.82,
      grounding_status: "grounded",
      evidence_canvas: {
        confidence: 0.82,
        why_this_answer: "Answer grounded in cited clause.",
        citations: [{ document_id: "doc-1", filename: "contract.pdf", page_number: 4, chunk_id: "chunk-1", snippet: "Termination may happen after breach.", content_type: "text" }],
        artifact_cards: [{ artifact_id: "risk-1", artifact_type: "risk", title: "Termination", filename: "contract.pdf", page_number: 4, text: "Material breach permits termination.", severity: "high" }],
        agent_steps: [{ agent_name: "LegalAgent", action: "contract_risk_context", output_summary: "Detected risk topics: termination." }],
      },
      agent_run: { steps: [] },
    };
    await route.fulfill({
      contentType: "text/event-stream",
      body: [
        'event: token\ndata: {"text":"The agreement has a termination risk. "}\n\n',
        `event: completed\ndata: ${JSON.stringify(final)}\n\n`,
      ].join(""),
    });
  });

  await login(page);
  await clickNav(page, /Chat/i, isMobile);
  await page.getByPlaceholder(/Ask about clauses/i).fill("What is the termination risk?");
  await page.getByPlaceholder(/Ask about clauses/i).press("Enter");

  await expect(page.getByText("The agreement has a termination risk.")).toBeVisible();
  await expect(page.getByText("grounded", { exact: true })).toBeVisible();
  await clickNav(page, /Evidence/i, isMobile);
  await expect(page.getByText("82%")).toBeVisible();
  await expect(page.getByText("Termination may happen after breach.")).toBeVisible();
  await expect(page.getByText("No graph evidence returned for this answer.")).toBeVisible();
});

test("sources upload and admin API key flows use existing backend contracts", async ({ page }) => {
  await mockBase(page);
  await page.route("**/workspaces/default/sources", async (route) => route.fulfill({ json: [{ job_id: "job-1", filename: "sample.pdf", status: "queued", progress: 5 }] }));
  await login(page);
  await page.goto("/sources");
  await page.setInputFiles("input[type=file]", {
    name: "sample.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("sample"),
  });
  await page.getByRole("button", { name: /Index sources/i }).click();
  await expect(page.getByText("sample.pdf")).toBeVisible();

  await page.goto("/admin");
  await page.getByRole("button", { name: /New key/i }).click();
  await expect(page.getByText("ak_live_secret")).toBeVisible();
  await page.getByRole("button", { name: "Revoke" }).click();
});

test("settings supports auth controls and theme persistence", async ({ page }) => {
  await mockBase(page);

  await page.goto("/settings");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Aiwana Founder")).toBeVisible();
  await page.locator("header").getByRole("button", { name: "Toggle theme" }).click();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", /light|dark/);
});

test("mobile navigation opens as a drawer", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile-only drawer assertion");
  await mockBase(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: /Chat/i })).toBeVisible();
});
