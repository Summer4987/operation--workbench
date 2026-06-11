import fs from "node:fs/promises";

const inputPath = process.argv[2] || "outputs/dianjin_automation/current_state_1040_all.json";
const outputPath = "dianjin-prototype/current_state.js";

const state = JSON.parse(await fs.readFile(inputPath, "utf8"));
await fs.writeFile(outputPath, `window.DIANJIN_CURRENT_STATE = ${JSON.stringify(state, null, 2)};\n`, "utf8");
console.log(JSON.stringify({
  inputPath,
  outputPath,
  currentRows: state.currentRows?.length || 0,
  recommendations: state.recommendations?.length || 0,
}, null, 2));
