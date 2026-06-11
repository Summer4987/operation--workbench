import fs from "node:fs/promises";
import vm from "node:vm";

const rulesPath = "dianjin-prototype/rules.js";
const outputPath = rulesPath;
const outputDir = "outputs/dianjin_automation";

async function latestProbeFile() {
  const files = await fs.readdir(outputDir);
  const matches = [];
  for (const file of files) {
    if (!file.startsWith("eleme_store_probe_") || !file.endsWith(".json")) continue;
    const path = `${outputDir}/${file}`;
    const stat = await fs.stat(path);
    matches.push({ path, mtime: stat.mtimeMs });
  }
  matches.sort((a, b) => b.mtime - a.mtime);
  return matches[0]?.path || null;
}

function shortName(fullName) {
  const match = String(fullName || "").match(/\(([^)]+)\)/);
  return match ? match[1].trim() : String(fullName || "").trim();
}

function normalizeName(name) {
  return String(name || "")
    .replace(/\s+/g, "")
    .replace(/^熊小小牛排饭POKEBEAR[（(]/i, "")
    .replace(/[）)]$/g, "");
}

const context = { window: {} };
vm.runInNewContext(await fs.readFile(rulesPath, "utf8"), context);
const rules = context.window.DIANJIN_RULES;

const probePath = await latestProbeFile();
if (!probePath) throw new Error("没有找到门店探测文件");
const probe = JSON.parse(await fs.readFile(probePath, "utf8"));
const tree = probe.apiSummaries?.find((item) => item.type === "restaurantTree");
const shops = (tree?.shops || []).filter((shop) => shop.restaurantType === "LEAF");
const byShortName = new Map(shops.map((shop) => [normalizeName(shortName(shop.name)), shop]));
const lowMinBidStores = new Set(rules.lowMinBidStores || []);

function minBidForStore(store) {
  if (Number.isFinite(Number(store.minBid))) return Number(store.minBid);
  return lowMinBidStores.has(store.name) ? 0.4 : rules.defaultMinBid ?? 0.5;
}

const enrichedStores = rules.stores.map((store) => {
  const match = byShortName.get(normalizeName(store.name));
  return {
    ...store,
    minBid: minBidForStore(store),
    shopId: match?.id || store.shopId || null,
    elemeFullName: match?.name || store.elemeFullName || "",
  };
});

const enrichedRules = {
  ...rules,
  enrichedAt: new Date().toISOString(),
  probeFile: probePath,
  stores: enrichedStores,
};

await fs.writeFile(outputPath, `window.DIANJIN_RULES = ${JSON.stringify(enrichedRules, null, 2)};\n`, "utf8");

console.log(JSON.stringify({
  probePath,
  storeCount: enrichedStores.length,
  matched: enrichedStores.filter((store) => store.shopId).length,
  missing: enrichedStores.filter((store) => !store.shopId).map((store) => store.name),
  stores: enrichedStores.map((store) => ({ name: store.name, shopId: store.shopId, elemeFullName: store.elemeFullName })),
}, null, 2));
