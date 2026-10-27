import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import path from "node:path";

const root = process.cwd();
const output = path.join(root, "proposal_evidence", "screens");
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();
page.setDefaultTimeout(30000);

async function shot(name, url) {
  await page.goto(`http://127.0.0.1:3000${url}`, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => undefined);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(output, name), fullPage: true });
}

const credentials = { email: "zimyo-demo@aiwana.local", password: "ZimyoDemo!2026", display_name: "Zimyo Demo Enterprise" };
let auth = await context.request.post("http://127.0.0.1:8000/auth/signup", { data: credentials });
if (!auth.ok()) auth = await context.request.post("http://127.0.0.1:8000/auth/login", { data: credentials });
if (!auth.ok()) throw new Error(`Demo authentication failed: ${auth.status()} ${await auth.text()}`);
const authPayload = await auth.json();
await context.addInitScript((token) => window.localStorage.setItem("aiwana_session_token", token), authPayload.session_token);
await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await shot("01_dashboard.png", "/");

await page.goto("http://127.0.0.1:3000/sources", { waitUntil: "networkidle" });
const input = page.locator('input[type="file"]');
await input.setInputFiles(path.join(root, "data", "demo_uploads", "03_aiwana_enterprise_policy_multimodal.pdf"));
await page.getByRole("button", { name: /Index sources/i }).click();
await page.waitForTimeout(3500);
await page.screenshot({ path: path.join(output, "02_document_upload.png"), fullPage: true });

await shot("03_chat_with_citations.png", "/chat");
await shot("04_evidence_view.png", "/evidence");
await shot("05_data_vault_overview.png", "/data-vault");
await shot("06_document_data_footprint.png", "/data-vault");
await shot("07_data_lineage.png", "/data-vault");
await shot("08_vector_index_chunks.png", "/data-vault");
await shot("09_privacy_processing_boundary.png", "/data-vault");
await shot("10_retention_policy.png", "/data-vault");
await shot("11_delete_everywhere.png", "/data-vault");
await shot("12_deletion_verification.png", "/data-vault");
await shot("13_deletion_receipt.png", "/data-vault");
await shot("14_admin_rbac.png", "/admin");
await shot("15_industry_packs.png", "/");
await shot("16_query_modes.png", "/chat");
await browser.close();
