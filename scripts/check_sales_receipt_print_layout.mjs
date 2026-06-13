import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PAGE_PATH = path.join(ROOT, "sales-receipt-generator", "index.html");
const OUTPUT_DIR = path.join(ROOT, "outputs", "sales_receipt_print_check");
const SCREENSHOT_PATH = path.join(OUTPUT_DIR, "latest.png");
const JSON_PATH = path.join(OUTPUT_DIR, "latest.json");
const PAGE_HEIGHT_PX = 1010;

function nowText() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

async function main() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1400 }, deviceScaleFactor: 1 });
  try {
    await page.goto(pathToFileURL(PAGE_PATH).href, { waitUntil: "networkidle" });
    await page.evaluate(() => {
      localStorage.clear();
      document.querySelector("#saleDate").value = "2026-06-13";
      document.querySelector("#receiptNo").value = "XXXS-20260613-001";
      document.querySelector("#buyerName").value = "熊小小示例收货单位";
      document.querySelector("#notes").value = "打印版式校验样例：含多行商品、备注和默认公章。";
      const rows = [...document.querySelectorAll("#itemRows .item-row")];
      const samples = [
        ["黑椒牛排饭套餐", "24", "份", "960"],
        ["儿童牛排饭套餐", "12", "份", "420"],
        ["门店物料补给", "3", "箱", ""],
        ["加盟培训资料", "1", "套", ""],
      ];
      while (document.querySelectorAll("#itemRows .item-row").length < samples.length) {
        document.querySelector("#addItem").click();
      }
      [...document.querySelectorAll("#itemRows .item-row")].forEach((row, index) => {
        const sample = samples[index] || ["", "", "", ""];
        row.querySelector(".item-name").value = sample[0];
        row.querySelector(".item-qty").value = sample[1];
        row.querySelector(".item-unit").value = sample[2];
        row.querySelector(".item-amount").value = sample[3];
      });
      document.querySelector("#receiptForm").dispatchEvent(new Event("input", { bubbles: true }));
      window.xiongSalesReceipt.prepareOnePagePrint();
    });

    const metrics = await page.evaluate((pageHeightPx) => {
      const receipt = document.querySelector("#receipt");
      const zoom = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--print-zoom")) || 1;
      const rect = receipt.getBoundingClientRect();
      const scaledHeight = Math.round(receipt.scrollHeight * zoom);
      const tableRows = document.querySelectorAll("#receiptBody tr").length;
      return {
        zoom,
        scroll_height: receipt.scrollHeight,
        rendered_height: Math.round(rect.height),
        scaled_height: scaledHeight,
        page_height_px: pageHeightPx,
        table_rows: tableRows,
        fits_one_page: scaledHeight <= pageHeightPx,
      };
    }, PAGE_HEIGHT_PX);

    await page.locator("#receipt").screenshot({ path: SCREENSHOT_PATH });
    const payload = {
      generated_at: nowText(),
      status: metrics.fits_one_page ? "ok" : "failed",
      message: metrics.fits_one_page
        ? "销售单打印版式校验通过：样例单据可压入一页。"
        : "销售单打印版式校验失败：样例单据超过一页高度。",
      screenshot: "outputs/sales_receipt_print_check/latest.png",
      source: "sales-receipt-generator/index.html",
      metrics,
    };
    await fs.writeFile(JSON_PATH, `${JSON.stringify(payload, null, 2)}\n`);
    await fs.chmod(JSON_PATH, 0o644);
    await fs.chmod(SCREENSHOT_PATH, 0o644);
    console.log(payload.message);
    if (payload.status !== "ok") process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`销售单打印版式校验失败：${error.message}`);
  process.exitCode = 1;
});
