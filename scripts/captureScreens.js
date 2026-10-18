/*
 * Captures the landing-page screenshots from the running app.
 *
 * This is the other half of server/scripts/seedDemo.js. That script makes the
 * DATA reproducible; this one makes the CAPTURE reproducible. Before both
 * existed, the screenshots in src/assets/screenshots/ were hand-taken, so they
 * drifted a whole market behind the app (US tickers in dollars long after the
 * code moved to NSE and rupees) and nobody noticed, because git cannot diff a
 * PNG. Now: `npm run seed` then `npm run screens` reproduces every asset.
 *
 * WHY A FIXED 1440x900 VIEWPORT AND NOT fullPage
 *
 * fullPage would stitch the entire scroll height into one very tall PNG, which
 * is useless in the ScreenShowcase two-column grid and would also drag in
 * whatever happens to be at the bottom of the page. A fixed viewport crops at
 * the fold, so "what the screenshot contains" is a property of this file rather
 * than of how long the seeded tables happen to be. 1440 matches the width of
 * the assets already committed, so the showcase layout stays calibrated.
 *
 * The flip side: the PageInsight card must FIT inside that 900px. It is the last
 * element on holdings, positions, orders and watchlist, so the seed keeps those
 * tables to five rows on purpose. Lengthen them and the card falls out of shot.
 *
 * WHY IT WAITS ON THE AI CARD INSTEAD OF SLEEPING
 *
 * PageInsight streams its text from Gemini token by token, so a fixed delay
 * photographs a half-written sentence, or the literal string "Analyzing...".
 * waitForInsight() below watches for the stream to both start and stop.
 *
 * Each run makes one Gemini call per insight page (four), which is well inside
 * the ~15/min quota — but it is not free, so don't put this in a loop.
 *
 * Needs Chrome already installed (puppeteer-core ships no browser). Override the
 * path with CHROME_PATH=... if yours lives somewhere unusual.
 *
 * Run it with:  npm run screens                 (all six, with both servers up)
 *               npm run screens -- holdings     (just the matching filenames)
 *
 * The `--` is required: without it npm keeps the argument for itself and you
 * silently get all six. The filter exists so one bad capture can be redone
 * without re-shooting the five that were fine, and without spending four more
 * Gemini calls on them.
 */

import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(ROOT, "src", "assets", "screenshots");

const APP_URL = process.env.APP_URL ?? "http://localhost:5173";
const DEMO_EMAIL = "demo@tradium.local";
const DEMO_PASSWORD = "demo1234";

const WIDTH = 1440;
const HEIGHT = 900;

/* The six screens the landing page shows, in the order ScreenShowcase lists
   them — the chart page leads, because it is the one that looks like a trading
   app at a glance.
 *
 * The dashboard is deliberately absent: Hero.jsx already uses it as the hero
 * image, so putting it here would show the same screen twice on one page.
 *
 * `insight` marks the pages that render a PageInsight card, which is the thing
 * we have to wait for. Instrument and Funds simply don't have one.
 *
 * `capture` names a data-capture element to clip to instead of the viewport —
 * used for the sector heatmap, whose squarified layout (50 tiles, sector
 * grouping, library-drawn) can't be reproduced as marketing DOM. The element
 * hook lives in Markets.jsx; move it there, not here, if the layout shifts. */
const SCREENS = [
  { file: "app-trade.png",     path: "/dashboard/instrument/RELIANCE", waitFor: "Key statistics",      insight: false, chart: true },
  { file: "app-holdings.png",  path: "/dashboard/holdings",            waitFor: "Current value",       insight: true },
  { file: "app-positions.png", path: "/dashboard/positions",           waitFor: "Gross exposure",      insight: true },
  { file: "app-orders.png",    path: "/dashboard/orders",              waitFor: "Executed turnover",   insight: true },
  { file: "app-watchlist.png", path: "/dashboard/watchlist",           waitFor: "Advancing",           insight: true },
  { file: "app-funds.png",     path: "/dashboard/funds",               waitFor: "Margin utilisation",  insight: false },
  { file: "app-markets.png",   path: "/dashboard/markets",             waitFor: "Breadth",             insight: true },
  { file: "app-heatmap.png",   path: "/dashboard/markets",             waitFor: "Breadth",             insight: false, capture: "sector-heatmap" },
];

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findChrome() {
  const found = CHROME_CANDIDATES.find((p) => existsSync(p));
  if (!found) {
    throw new Error(
      "No Chrome or Edge found. Set CHROME_PATH to your browser executable.",
    );
  }
  return found;
}

/* Reads the PageInsight card's one line of text, or null when the card isn't on
   the page. The card is the only `bg-foreground` + `text-background` block in
   the app, which makes it easy to find without adding a test id to the JSX. */
function readInsight() {
  const card = document.querySelector("div.bg-foreground.text-background");
  const p = card?.querySelector("p");
  return p ? p.textContent.trim() : null;
}

/* PageInsight shows one of these while it waits on the network, so seeing one is
   the same as seeing nothing. They are copied from PageInsight.jsx — if the copy
   there changes, this list has to change with it or captures will race. */
const PLACEHOLDERS = [
  "Analyzing...",
  "Reading your portfolio...",
  "Insight unavailable right now.",
];

/* Waits for the streamed insight to both arrive and finish.
 *
 * The AI SDK gives the DOM no done-flag to read — useCompletion just appends
 * tokens to `completion` — so "finished" has to be inferred. This checks TWO
 * independent things, because either one alone gives false positives:
 *
 *   1. The text stopped growing. Necessary, but not sufficient: Gemini's stream
 *      stalls mid-sentence for a second or more all the time, so stability by
 *      itself once photographed "...primarily dragged by BHARTIARTL dropping".
 *   2. The text ends in sentence punctuation. Every insight is a full sentence,
 *      so a truncated one fails this no matter how long the stream hangs.
 *
 * Both together, and the 6-read window (~2.1s) on top, is close to airtight. */
const SETTLED = /[.!?]$/;

async function waitForInsight(page, label) {
  const deadline = Date.now() + 45_000;
  let last = null;
  let stableReads = 0;

  while (Date.now() < deadline) {
    const text = await page.evaluate(readInsight);

    if (text && !PLACEHOLDERS.includes(text)) {
      if (text === last) stableReads++;
      else stableReads = 0;
      last = text;
      if (stableReads >= 6 && SETTLED.test(text)) return text;
    }

    await sleep(350);
  }

  // Not fatal: a rate-limited or slow insight still produces a usable screenshot
  // of the page, it just won't show the card's final sentence. Say so loudly
  // rather than silently shipping a "Analyzing..." screenshot.
  console.warn(`  ! ${label}: insight never settled — check the card in the PNG`);
  return last;
}

/* Writes the PNG, retrying on the transient lock Windows throws here.
 *
 * On Windows these writes intermittently fail with errno -4094 (UV_UNKNOWN) on
 * open, because something else is holding the file for a moment — Defender
 * scanning the previous write, a Vite watcher, or an Explorer thumbnailer. It is
 * always gone within a second, and it hits one file out of six at random, so
 * failing the whole run over it would make the script feel broken when it isn't.
 *
 * Note this takes the screenshot into memory first and writes it separately;
 * page.screenshot({ path }) does both at once, which would mean re-shooting the
 * page on every retry. */
async function writePng(path, bytes) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      await writeFile(path, bytes);
      return;
    } catch (err) {
      if (attempt === 5) throw err;
      console.warn(`  ! write locked (${err.code}) — retry ${attempt}/4`);
      await sleep(600 * attempt);
    }
  }
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  // `npm run screens holdings positions` shoots only those two. No args = all six.
  const filters = process.argv.slice(2);
  const targets = filters.length
    ? SCREENS.filter((s) => filters.some((f) => s.file.includes(f)))
    : SCREENS;

  if (!targets.length) {
    throw new Error(
      `No screen matched ${filters.join(", ")}. Known: ${SCREENS.map((s) => s.file).join(", ")}`,
    );
  }

  const executablePath = findChrome();
  console.log(`Using browser: ${executablePath}`);

  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    // --hide-scrollbars keeps the OS scrollbar strip out of the right edge of
    // every capture, which would otherwise show up inside the browser frame the
    // showcase draws around these images.
    args: ["--hide-scrollbars", "--force-device-scale-factor=1"],
    defaultViewport: { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 },
  });

  try {
    const page = await browser.newPage();

    console.log(`Logging in as ${DEMO_EMAIL}...`);
    await page.goto(`${APP_URL}/login`, { waitUntil: "networkidle2" });
    await page.type("#email", DEMO_EMAIL);
    await page.type("#password", DEMO_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForFunction(
      () => location.pathname.startsWith("/dashboard"),
      { timeout: 30_000 },
    );
    console.log("Logged in.\n");

    for (const screen of targets) {
      console.log(`${screen.file}`);
      await page.goto(`${APP_URL}${screen.path}`, { waitUntil: "networkidle2" });

      // Wait for something only the loaded page renders, so we never shoot the
      // "Loading..." state each dashboard page shows first. textContent, not
      // innerText: innerText applies CSS text-transform, so an `uppercase`
      // header would come back as "CURRENT VALUE" and never match.
      await page
        .waitForFunction(
          (needle) => document.body.textContent.includes(needle),
          { timeout: 30_000 },
          screen.waitFor,
        )
        .catch(() => console.warn(`  ! never saw "${screen.waitFor}"`));

      if (screen.insight) {
        const text = await waitForInsight(page, screen.file);
        if (text) console.log(`  insight: "${text.slice(0, 72)}..."`);
      }

      // lightweight-charts draws to a canvas after layout settles, and the
      // entrance animations are ~200ms, so give the paint a beat either way.
      await sleep(screen.chart ? 2500 : 900);
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(250);

      const out = join(OUT_DIR, screen.file);
      let bytes;

      if (screen.capture) {
        // Element capture: clip to one component rather than the viewport. The
        // element is scrolled into view first — scrollTo(0,0) above left it
        // below the fold on pages taller than 900px, and a clip outside the
        // viewport photographs whatever happens to be there instead.
        const handle = await page.$(`[data-capture="${screen.capture}"]`);
        if (!handle) throw new Error(`No [data-capture="${screen.capture}"] on ${screen.path}`);
        await handle.scrollIntoView();
        await sleep(250);
        bytes = await handle.screenshot({ type: "png" });
      } else {
        bytes = await page.screenshot({ type: "png" });
      }
      await writePng(out, bytes);

      const { height, insightTop } = await page.evaluate(() => {
        const card = document.querySelector("div.bg-foreground.text-background");
        return {
          height: document.documentElement.scrollHeight,
          insightTop: card ? Math.round(card.getBoundingClientRect().top) : null,
        };
      });

      // The whole reason the seed keeps tables short. If the card's top is below
      // the fold it is not in the picture, and the capture is wrong even though
      // the file wrote fine.
      if (screen.insight) {
        const visible = insightTop !== null && insightTop < HEIGHT - 40;
        console.log(
          `  page ${height}px · card top y=${insightTop} · ${visible ? "card IN frame" : "CARD OUT OF FRAME"}`,
        );
        if (!visible) process.exitCode = 1;
      } else {
        console.log(`  page ${height}px`);
      }
    }

    console.log(`\nWrote ${SCREENS.length} screenshots to src/assets/screenshots/`);
    if (process.exitCode === 1) {
      console.log("One or more insight cards fell outside the 900px viewport.");
      console.log("Shorten the arrays in server/scripts/seedDemo.js and re-run.");
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
