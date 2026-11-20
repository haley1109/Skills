import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { compareAbaRanks, searchUrl, writeSearchLinks, writeTable } from "./合并词库.mjs";

import { loadArtifact, pythonCommand } from "./runtime.mjs";

const inputTab = "待筛查词库";
const outputTab = "词库";
const grades = ["强相关", "相关", "不相关"];
const gradeColors = [
  { fill: "#F4B183", font: { color: "#542801", bold: true } },
  { fill: "#A9D18E", font: { color: "#173510", bold: true } },
  { fill: "#595959", font: { color: "#FFFFFF", bold: true } },
];
const columnWidths = new Map([
  ["SEARCH", 12], ["亚马逊搜索网址", 41], ["流量词", 43],
  ["周搜索量", 13], ["ABA排名", 14], ["西柚点击转化率", 18],
  ["词来源", 33], ["西柚ABA排名", 16], ["指标差异", 29], ["西柚ABA报告周", 27],
  ["中文翻译", 27], ["相关性", 15], ["相关性依据", 22],
]);

const sources = [
  "亚马逊首页（用户实查）", "亚马逊首页", "西柚历史自然首页",
  "西柚自然位样本", "ABA商品辅助初判", "词义初判",
];

function sourceGroup(basis) {
  const label = basis.replace(/\s+/gu, "").replaceAll("(", "（").replaceAll(")", "）");
  return sources.find((source) => label.startsWith(source)) ?? "其他依据";
}

function parseRatings(payload) {
  if (!Array.isArray(payload.rows)) throw new Error("筛查结果须含 rows 数组");
  const byKeyword = new Map();
  for (const { keyword, grade, basis } of payload.rows) {
    if (typeof keyword !== "string" || !keyword.trim() || byKeyword.has(keyword)) {
      throw new Error("筛查结果流量词为空或重复");
    }
    if (!grades.includes(grade) || typeof basis !== "string" || !basis.trim()) {
      throw new Error(`缺少有效的相关性档位或依据：${keyword}`);
    }
    byKeyword.set(keyword, { grade, basis });
  }
  return byKeyword;
}

function readKeywordSheet(values, ratings, translations) {
  const headerRow = values.findIndex((row) => row.includes("流量词") && row.includes("ABA排名"));
  if (headerRow < 0) throw new Error("找不到流量词和 ABA排名 表头");
  const sourceHeader = values[headerRow];
  const keywordColumn = sourceHeader.indexOf("流量词");
  const rankColumn = sourceHeader.indexOf("ABA排名");
  const fields = sourceHeader.map((header, index) => ({ header, index })).filter(({ header }) =>
    typeof header === "string" && header !== "" && header !== "SEARCH" && header !== "亚马逊搜索网址");
  const sourceRows = values.slice(headerRow + 1).filter((row) => typeof row[keywordColumn] === "string"
    && row[keywordColumn].trim());
  if (!sourceRows.length || new Set(sourceRows.map((row) => row[keywordColumn])).size !== sourceRows.length) {
    throw new Error("待筛查词库为空，或含重复流量词");
  }
  sourceRows.sort((left, right) => compareAbaRanks(left[rankColumn], right[rankColumn]));
  const counts = new Map(grades.map((grade) => [grade, 0]));
  const basisCounts = new Map();
  const translatedFieldIndex = fields.findIndex(({ index }) => index === keywordColumn) + 1;
  const rows = sourceRows.map((row) => {
    const keyword = row[keywordColumn];
    const rating = ratings.get(keyword);
    const translation = Object.hasOwn(translations, keyword) ? translations[keyword] : null;
    if (!rating || typeof translation !== "string" || !translation.trim()) {
      throw new Error(`缺少判断或中文翻译：${keyword}`);
    }
    counts.set(rating.grade, counts.get(rating.grade) + 1);
    const group = sourceGroup(rating.basis);
    basisCounts.set(group, (basisCounts.get(group) ?? 0) + 1);
    const values = fields.map(({ index }) => row[index]);
    values.splice(translatedFieldIndex, 0, translation);
    return [null, searchUrl(keyword), ...values, rating.grade, rating.basis];
  });
  const headers = fields.map(({ header }) => header);
  headers.splice(translatedFieldIndex, 0, "中文翻译");
  return {
    headers: ["SEARCH", "亚马逊搜索网址", ...headers, "相关性", "相关性依据"],
    rows, counts, basisCounts,
  };
}

function addRatingSheet(workbook, sourceRows, ratings, translations, payload) {
  const { headers, rows, counts, basisCounts } = readKeywordSheet(sourceRows, ratings, translations);
  const sheet = workbook.worksheets.add(outputTab);
  sheet.showGridLines = false;
  sheet.tabColor = "#16495B";
  const summary = grades.map((grade) => `${grade} ${counts.get(grade)}`).join(" · ");
  const sourceSummary = [...basisCounts.entries()].map(([label, count]) => `${label} ${count}`).join(" · ");
  const period = typeof payload.period === "string" && payload.period ? ` · ${payload.period}` : "";
  sheet.getRange("A1:A3").values = [
    [outputTab],
    [`已判断 ${rows.length} 词 · ${summary}`],
    [`判断依据${period} · ${sourceSummary}`],
  ];
  sheet.getRange("A1").format.font = { name: "Aptos", size: 17, bold: true, color: "#16495B" };
  sheet.getRange("A1").format.rowHeight = 27;
  sheet.getRange("A2:A3").format.rowHeight = 21;
  sheet.getRange("A2").format.font = { name: "Aptos", bold: true, color: "#16495B" };
  sheet.getRange("A3").format.font = { name: "Aptos", size: 10, color: "#48616C" };
  sheet.freezePanes.freezeRows(4);
  const widths = headers.map((header) => columnWidths.get(header) ?? (header.includes("自然位") ? 22 : 18));
  writeTable(sheet, 3, 0, headers, rows, widths, "ScreenedKeywords");
  writeSearchLinks(sheet, 4, 0, rows.length);
  const gradeColumn = headers.indexOf("相关性");
  const gradeCells = sheet.getRangeByIndexes(4, gradeColumn, rows.length, 1);
  gradeCells.format.horizontalAlignment = "center";
  const firstCell = sheet.getCell(4, gradeColumn).address.split("!").at(-1).replaceAll("$", "");
  for (const [index, grade] of grades.entries()) {
    gradeCells.conditionalFormats.addCustom(`=${firstCell}="${grade}"`, gradeColors[index]);
  }
  console.log(`词库共 ${rows.length} 词。${summary}。${sourceSummary}。`);
  return sheet;
}

async function readSourceRows(inputPath, pythonPath) {
  const reader = `
import json, sys
from openpyxl import load_workbook

workbook = load_workbook(sys.argv[1], read_only=True, data_only=True)
try:
    if sys.argv[2] not in workbook.sheetnames:
        sys.exit("找不到「" + sys.argv[2] + "」")
    print(json.dumps(list(workbook[sys.argv[2]].values), default=str))
finally:
    workbook.close()
`;
  const { stdout } = await promisify(execFile)(pythonPath, ["-c", reader, inputPath, inputTab],
    { maxBuffer: 32 * 1024 * 1024 });
  return JSON.parse(stdout);
}

async function main() {
  const [inputFile, ratingsFile, translationsFile, outputFile, ...rest] = process.argv.slice(2);
  if (!inputFile || !ratingsFile || !translationsFile || !outputFile || rest.length) {
    throw new Error("用法：node 筛查词库.mjs <完整操作表.xlsx> <筛查结果.json> <中文翻译.json> <输出.xlsx>");
  }
  const inputPath = await fs.realpath(inputFile);
  const outputPath = path.resolve(outputFile);
  const originalInput = await fs.readFile(inputPath);
  const { SpreadsheetFile, Workbook } = await loadArtifact();
  const workbook = Workbook.create();
  const pythonPath = pythonCommand();
  const sourceRows = await readSourceRows(inputPath, pythonPath);
  const payload = JSON.parse(await fs.readFile(ratingsFile, "utf8"));
  const translations = JSON.parse(await fs.readFile(translationsFile, "utf8"));
  addRatingSheet(workbook, sourceRows, parseRatings(payload), translations, payload);
  workbook.recalculate();
  const outputDir = path.dirname(outputPath);
  await fs.mkdir(outputDir, { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  const staging = await fs.mkdtemp(path.join(outputDir, ".keywords-"));
  try {
    const authoredSheet = path.join(staging, "screened-sheet.xlsx");
    const combinedWorkbook = path.join(staging, "operation-workbook.xlsx");
    await output.save(authoredSheet);
    const mergeTool = fileURLToPath(new URL("./并入词库.py", import.meta.url));
    const { stdout } = await promisify(execFile)(pythonPath, [mergeTool, inputPath, authoredSheet, combinedWorkbook]);
    if (!originalInput.equals(await fs.readFile(inputPath))) {
      throw new Error("源工作簿在生成期间发生变化，需要从最新版本重新生成");
    }
    await fs.rename(combinedWorkbook, outputPath);
    console.log(stdout.trim());
  } finally {
    await fs.rm(staging, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
