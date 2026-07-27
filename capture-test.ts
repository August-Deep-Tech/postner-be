import { Stagehand } from "@browserbasehq/stagehand";
import dotenv from "dotenv";
import * as fs from "fs";
import * as path from "path";

dotenv.config({ path: ".env" });

interface CaptureStep {
  step: number;
  action: string;
  page: string;
  screenshot: string;
}

function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required env var: ${name}. Copy .env.example to .env and fill it in.`);
  }
  return value;
}

async function main() {
  const appUrl = requireEnv("APP_URL");
  const appEmail = requireEnv("APP_EMAIL");
  const appPassword = requireEnv("APP_PASSWORD");

  if (
    appUrl.includes("your-app-url.com") ||
    appEmail === "test-account-email" ||
    appPassword === "test-account-password"
  ) {
    throw new Error(
      "APP_URL / APP_EMAIL / APP_PASSWORD still look like placeholders. Update .env with real credentials."
    );
  }

  const hasOpenAI = Boolean(process.env.OPENAI_API_KEY?.trim());
  const hasAnthropic = Boolean(process.env.ANTHROPIC_API_KEY?.trim());
  if (!hasOpenAI && !hasAnthropic) {
    throw new Error("Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env for Stagehand.");
  }

  const model =
    process.env.STAGEHAND_MODEL?.trim() ||
    (hasAnthropic ? "anthropic/claude-sonnet-4-6" : "openai/gpt-4o");

  console.log(`Starting Stagehand (LOCAL) with model=${model}`);
  console.log(`Target: ${appUrl}`);

  const stagehand = new Stagehand({
    env: "LOCAL",
    model,
  });

  await stagehand.init();
  const page = stagehand.context.pages()[0];

  const captureDir = path.join(process.cwd(), "captures");
  fs.mkdirSync(captureDir, { recursive: true });

  const manifest: CaptureStep[] = [];

  async function captureStep(step: number, action: string) {
    const filename = `step-${step}.png`;
    const absolutePath = path.join(captureDir, filename);
    const relativePath = path.join("captures", filename).replace(/\\/g, "/");

    const image = await page.screenshot({ fullPage: true });
    fs.writeFileSync(absolutePath, image);

    const entry: CaptureStep = {
      step,
      action,
      page: page.url(),
      screenshot: relativePath,
    };
    manifest.push(entry);
    console.log(`[step ${step}] ${action}`);
    console.log(`         page: ${entry.page}`);
    console.log(`         shot: ${relativePath}`);
  }

  try {
    // --- Login ---
    console.log("Navigating to app...");
    await page.goto(appUrl);
    console.log("Logging in...");
    await stagehand.act(
      `Log in with email ${appEmail} and password ${appPassword}`
    );
    console.log(`Logged in. Current URL: ${page.url()}`);

    // --- Flow steps (natural-language acts — adjust if UI labels differ) ---
    console.log("Step 1: click Classwork cell...");
    await stagehand.act("Click a Classwork cell to begin entering a score");
    await captureStep(1, "Click a Classwork cell and start entering a score");

    console.log("Step 2: enter score...");
    await stagehand.act(
      "Type a score value into the Classwork cell and confirm it so the grade and average update on screen"
    );
    await captureStep(2, "Type the score — grade and average update");

    console.log("Step 3: open Results Generate...");
    await stagehand.act(
      'Navigate to "Results Generate" (or the equivalent results / report generation screen)'
    );
    await captureStep(3, "Open Results Generate to preview class reports");

    console.log("Step 4: generate classroom teacher feedback...");
    await stagehand.act(
      'Trigger "Generate classroom teacher feedback" (or the button that generates class feedback from grades)'
    );
    await captureStep(4, "Generate classroom teacher feedback from the grades");

    console.log("Step 5: open student report card preview...");
    await stagehand.act("Open a student's full report card preview");
    await captureStep(5, "Preview a student's full report card");

    const manifestPath = path.join(captureDir, "manifest.json");
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    console.log(`Done. Wrote ${manifest.length} steps to ${manifestPath}`);
  } finally {
    await stagehand.close();
  }
}

main().catch((err) => {
  console.error("capture-test failed:", err);
  process.exit(1);
});
