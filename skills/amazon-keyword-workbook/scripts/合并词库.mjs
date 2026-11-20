import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { loadArtifact, pythonCommand } from "./runtime.mjs";

const sourceNames = ["ABA正向查找", "ABA反向查找"];
const competitorSheetName = "竞品反查";
const resultSheetName = "待筛查词库";
const asinPattern = /^[A-Z0-9]{10}$/u;
const statuses = { complete: "已查完", partial: "部分取得", pending: "待查询" };
const metrics = ["searchVolume", "abaRank", "clickConversionRate"];
const metricLabels = ["周搜索量", "西柚ABA排名", "西柚点击转化率"];

function requiredSheet(workbook, name) {
  const sheet = workbook.worksheets.items.find((item) => item.name === name);
  if (!sheet) throw new Error(`找不到工作表「${name}」`);
  return sheet;
}

function requireKeyword(value, location) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${location} 缺少有效流量词`);
  }
  return value;
}

export function searchUrl(keyword) {
  const query = encodeURIComponent(requireKeyword(keyword, "亚马逊搜索网址"))
    .replace(/[!'()*]/gu, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
  return `https://www.amazon.com/s?k=${query}`;
}

export function compareAbaRanks(leftRank, rightRank) {
  const hasLeft = Number.isSafeInteger(leftRank) && leftRank > 0;
  const hasRight = Number.isSafeInteger(rightRank) && rightRank > 0;
  if (hasLeft && hasRight) return leftRank - rightRank;
  return Number(hasRight) - Number(hasLeft);
}

function readMetric(value, field, location) {
  if (value == null || value === "" || value === "N") return null;
  const valid = field.endsWith("Rate")
    ? Number.isFinite(value) && value >= 0 && value <= 1
    : Number.isSafeInteger(value) && value >= (field === "searchVolume" ? 0 : 1);
  if (!valid) throw new Error(`${location} 的 ${field} 格式无效`);
  return value;
}

function readAsins(workbook) {
  const sheet = requiredSheet(workbook, "竞品ASIN列表");
  const rows = sheet.getUsedRange(true)?.values ?? [];
  const results = new Set();
  for (const [index, row] of rows.entries()) {
    const value = row[0];
    if (value == null || value === "") {
      if (row[1]) throw new Error(`竞品ASIN列表第 ${index + 1} 行缺少 ASIN`);
      continue;
    }
    if (index === 0 && ["ASIN", "竞品ASIN", "父ASIN", "父 ASIN"].includes(value)) continue;
    if (!asinPattern.test(value)) throw new Error(`竞品ASIN列表第 ${index + 1} 行 ASIN 无效`);
    results.add(value);
  }
  if (results.size === 0) throw new Error("竞品ASIN列表没有 ASIN");
  return [...results];
}

function readAba(workbook, terms) {
  let rowCount = 0;
  for (const name of sourceNames) {
    const rows = requiredSheet(workbook, name).getUsedRange(true)?.values ?? [];
    const [headers, ...entries] = rows;
    const termColumn = headers?.indexOf("搜索词") ?? -1;
    const rankColumn = headers?.indexOf("搜索频率排名") ?? -1;
    if (termColumn < 0 || rankColumn < 0) throw new Error(`「${name}」缺少 ABA 表头`);
    for (const [index, row] of entries.entries()) {
      if (row.every((value) => value == null || value === "")) continue;
      const location = `${name} 第 ${index + 2} 行`;
      const keyword = requireKeyword(row[termColumn], location);
      const rank = readMetric(row[rankColumn], "abaRank", location);
      termEntry(terms, keyword).aba.push({ source: name, rank });
      rowCount++;
    }
  }
  return rowCount;
}

function termEntry(terms, keyword) {
  if (!terms.has(keyword)) {
    terms.set(keyword, { aba: [], competitors: new Map(), marketMetrics: null });
  }
  return terms.get(keyword);
}

function addCapture(capture, asins, terms) {
  if (capture.marketplace !== "US" || !Array.isArray(capture.competitors)) {
    throw new Error("西柚结果须为 US 站，并包含 competitors 数组");
  }
  const included = new Map();
  const parents = new Set();
  const parentsWithRows = new Set();
  for (const item of capture.competitors) {
    const { inputAsin, parentAsin, status, rows } = item;
    if (!asins.includes(inputAsin) || included.has(inputAsin)
        || !Object.hasOwn(statuses, status) || !Array.isArray(rows)) {
      throw new Error(`竞品查询记录无效或重复，输入 ASIN ${inputAsin}`);
    }
    if ((parentAsin != null && !asinPattern.test(parentAsin))
        || (status !== "pending" && !parentAsin) || (status === "pending" && rows.length)) {
      throw new Error(`竞品 ${inputAsin} 的父 ASIN、查询状态或词条不一致`);
    }
    if (status !== "pending" && (typeof capture.period !== "string" || !capture.period.trim())) {
      throw new Error("已进行竞品查询时须记录 period");
    }
    included.set(inputAsin, { parentAsin, status, keywords: new Set() });
    if (parentAsin) parents.add(parentAsin);
    if (status !== "pending") {
      if (parentsWithRows.has(parentAsin)) {
        throw new Error(`同一父体 ${parentAsin} 的结果只导入一次`);
      }
      parentsWithRows.add(parentAsin);
    }
    for (const [index, row] of rows.entries()) {
      const location = `${parentAsin} 第 ${index + 1} 条西柚结果`;
      const keyword = requireKeyword(row.keyword, location);
      const entry = termEntry(terms, keyword);
      const values = Object.fromEntries([...metrics, "organicRank"].map((field) => [
        field, readMetric(row[field], field, location),
      ]));
      if (!entry.competitors.has(parentAsin)) entry.competitors.set(parentAsin, []);
      entry.competitors.get(parentAsin).push(values);
      included.get(inputAsin).keywords.add(keyword);
    }
  }
  if (capture.keywordMetrics != null && !Array.isArray(capture.keywordMetrics)) {
    throw new Error("keywordMetrics 须为数组");
  }
  const seenMetrics = new Set();
  for (const [index, row] of (capture.keywordMetrics ?? []).entries()) {
    const location = `第 ${index + 1} 条西柚关键词指标`;
    const keyword = requireKeyword(row.keyword, location);
    if (seenMetrics.has(keyword)) throw new Error(`${location} 重复：${keyword}`);
    seenMetrics.add(keyword);
    const entry = terms.get(keyword);
    if (entry) {
      entry.marketMetrics = Object.fromEntries(metrics.map((field) => [
        field, readMetric(row[field], field, location),
      ]));
      if (typeof row.metricsDate === "string" && row.metricsDate.length <= 100) {
        entry.marketMetrics.metricsDate = row.metricsDate;
      }
    }
  }
  const columns = [...new Set(asins.map((asin) => included.get(asin)?.parentAsin ?? asin))];
  const captureStatus = asins.map((asin) => {
    const item = included.get(asin);
    const duplicate = item?.status === "pending" && parentsWithRows.has(item.parentAsin);
    return [
      asin, item?.parentAsin ?? null,
      duplicate ? "复用同父体" : statuses[item?.status ?? "pending"],
      item && item.status !== "pending" ? item.keywords.size : null,
    ];
  });
  const complete = asins.every((asin) => {
    const item = included.get(asin);
    if (item?.status === "complete") return true;
    return item?.status === "pending" && [...included.values()].some((source) =>
      source.parentAsin === item.parentAsin && source.status === "complete");
  });
  return { columns, parents, captureStatus, complete, queried: parentsWithRows.size };
}

function uniqueValue(values, label, conflicts) {
  const unique = [...new Set(values.filter(({ value }) => value != null).map(({ value }) => value))];
  if (unique.length <= 1) return unique[0] ?? null;
  const detail = [...new Set(values.filter(({ value }) => value != null).map(({ source, value }) =>
    `${source} ${value}`))].join(" / ");
  conflicts.push(`${label} [${detail}]`);
  return "冲突";
}

function buildRows(terms, competitors, separateMarketPeriods) {
  const result = [];
  const competitorRows = [];
  for (const [keyword, entry] of terms) {
    const conflicts = [];
    const sourceValues = [...entry.competitors].flatMap(([source, rows]) =>
      rows.map((row) => ({ source, row })));
    const [searchVolume, xydcAbaRank, clickConversionRate] = metrics.map((key, index) => {
      const separateMetric = entry.marketMetrics?.[key];
      const parentValues = sourceValues.map(({ source, row }) => ({ source, value: row[key] }));
      if (separateMetric == null) return uniqueValue(parentValues, metricLabels[index], conflicts);
      if (separateMarketPeriods && parentValues.some(({ value }) => value != null)) {
        const observed = [...new Set(parentValues.filter(({ value }) => value != null)
          .map(({ source, value }) => `${source} ${value}`))];
        conflicts.push(`${metricLabels[index]} [关键词指标 ${separateMetric} / 父体反查 ${observed.join(" / ")}]`);
      } else {
        uniqueValue([{ source: "西柚关键词指标", value: separateMetric }, ...parentValues],
          metricLabels[index], conflicts);
      }
      return separateMetric;
    });
    const organic = competitors.columns.map((asin) => uniqueValue(
      (entry.competitors.get(asin) ?? []).map(({ organicRank: value }) => ({ source: asin, value })),
      `${asin} 自然位`, conflicts,
    ));
    if (entry.competitors.size) {
      competitorRows.push([
        keyword, searchVolume, xydcAbaRank ?? "N", clickConversionRate ?? "N",
        ...organic, [...entry.competitors.keys()].join("、"), conflicts.join(" ｜ "),
        entry.marketMetrics?.metricsDate ?? null,
      ]);
    }
    const directRank = uniqueValue(entry.aba.map(({ source, rank: value }) => ({ source, value })),
      "原表ABA排名", conflicts);
    if (typeof directRank === "number" && typeof xydcAbaRank === "number" && directRank !== xydcAbaRank) {
      conflicts.push("原表与西柚 ABA 排名不同");
    }
    const sources = [...new Set(entry.aba.map(({ source }) => source))];
    if (entry.competitors.size) sources.push(competitorSheetName);
    result.push([
      keyword, searchVolume, directRank ?? xydcAbaRank ?? "N", clickConversionRate ?? "N", ...organic,
      sources.join("、"), xydcAbaRank ?? "N", conflicts.join(" ｜ "),
      entry.marketMetrics?.metricsDate ?? null,
    ]);
  }
  return { result, competitorRows };
}

export function writeTable(sheet, startRow, startCol, headers, rows, widths, tableName) {
  const grid = sheet.getRangeByIndexes(startRow, startCol, rows.length + 1, headers.length);
  grid.format.font = { name: "Aptos", size: 11, color: "#172B36" };
  grid.format.rowHeight = 19;
  const head = sheet.getRangeByIndexes(startRow, startCol, 1, headers.length);
  head.values = [headers];
  if (rows.length > 0 && tableName) {
    const table = sheet.tables.add(grid, true, tableName);
    table.style = "TableStyleMedium2";
    table.showBandedRows = true;
  }
  head.format.fill = "#16495B";
  head.format.font = { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" };
  head.format.rowHeight = 26;
  head.format.verticalAlignment = "center";
  head.format.horizontalAlignment = "center";
  if (rows.length) {
    const cellValues = rows.map((row) => row.map((value) =>
      typeof value === "string" && value.startsWith("=") ? `'${value}` : value));
    sheet.getRangeByIndexes(startRow + 1, startCol, rows.length, headers.length).values = cellValues;
  }
  for (const [index, heading] of headers.entries()) {
    const range = grid.getColumn(index);
    range.format.columnWidth = widths[index];
    const percent = heading.includes("转化率");
    const count = /搜索量|排名|自然位|原文词数/u.test(heading);
    if (percent || count) {
      range.setNumberFormat(percent ? "0.00%" : "#,##0");
      range.format.horizontalAlignment = "center";
    }
  }
}

export function writeSearchLinks(sheet, dataStartRow, startCol, rowCount) {
  if (!rowCount) return;
  const urls = sheet.getRangeByIndexes(dataStartRow, startCol + 1, rowCount, 1);
  const urlColumn = sheet.getRangeByIndexes(dataStartRow, startCol + 1, 1, 1).address.replace(/\d+$/u, "");
  const links = sheet.getRangeByIndexes(dataStartRow, startCol, rowCount, 1);
  links.formulas = urls.values.map(([url], index) => [
    url ? `=HYPERLINK(${urlColumn}${dataStartRow + index + 1},"SEARCH")` : "",
  ]);
  links.format.font = { name: "Aptos", size: 11, color: "#0563C1" };
  links.format.horizontalAlignment = "center";
}

function addOutputSheet(workbook, name, status, detail, ready) {
  if (workbook.worksheets.items.some((item) => item.name === name)) {
    throw new Error(`输入已有「${name}」，请使用三张源表所在的原始文件`);
  }
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.tabColor = name === resultSheetName ? "#16495B" : "#467987";
  sheet.getRange("A1:A3").values = [[name], [status], [detail]];
  sheet.getRange("A1").format.font = { name: "Aptos", size: 17, bold: true, color: "#16495B" };
  sheet.getRange("A1").format.rowHeight = 27;
  sheet.getRange("A2").format.font = { name: "Aptos", bold: true, color: ready ? "#16495B" : "#9B4E00" };
  sheet.getRange("A2:A3").format.rowHeight = 21;
  sheet.getRange("A3").format.font = { name: "Aptos", size: 10, color: "#48616C" };
  sheet.freezePanes.freezeRows(4);
  return sheet;
}

async function main() {
  const [inputFile, outputFile, flag, captureFile, ...extraArgs] = process.argv.slice(2);
  if (!inputFile || !outputFile || (flag && (flag !== "--xydc" || !captureFile)) || extraArgs.length) {
    throw new Error("用法：node 合并词库.mjs <原始词库.xlsx> <输出.xlsx> [--xydc 西柚结果.json]");
  }
  const inputPath = await fs.realpath(inputFile);
  const outputPath = path.resolve(outputFile);
  if (inputPath === outputPath || await fs.realpath(outputPath).catch(() => null) === inputPath) {
    throw new Error("输出文件须使用不同路径");
  }
  const { FileBlob, SpreadsheetFile, Workbook } = await loadArtifact();
  const initialSource = await fs.readFile(inputPath);
  const source = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
  for (const name of [competitorSheetName, resultSheetName]) {
    if (source.worksheets.items.some((sheet) => sheet.name === name)) {
      throw new Error(`原操作表已有「${name}」，请从当前三张源表的副本开始`);
    }
  }
  const resultBook = Workbook.create();
  const competitorBook = Workbook.create();
  const terms = new Map();
  const asins = readAsins(source);
  const abaRowCount = readAba(source, terms);
  const abaUniqueCount = terms.size;
  const capture = captureFile ? JSON.parse(await fs.readFile(captureFile, "utf8"))
    : { marketplace: "US", competitors: [] };
  const competitors = addCapture(capture, asins, terms);
  const { result, competitorRows } = buildRows(terms, competitors,
    Boolean(capture.metricsPeriod && capture.metricsPeriod !== capture.period));

  const rankHeaders = competitors.columns.map((asin) =>
    `${asin} 自然位${competitors.parents.has(asin) ? "" : "（待核父体）"}`);
  const rankWidths = competitors.columns.map((asin) => competitors.parents.has(asin) ? 22 : 31);
  const period = capture.period || "待查询";
  const metricsPeriod = capture.metricsPeriod || (competitors.queried > 0 ? "见西柚返回" : "待查询");
  const resultStatus = competitors.complete
    ? `ABA 与西柚竞品词已汇总，共 ${result.length} 个原文词`
    : `当前共 ${result.length} 个原文词，西柚竞品反查尚未完成`;
  const resultSheet = addOutputSheet(resultBook, resultSheetName, resultStatus,
    `ABA ${abaRowCount} 条 → ${abaUniqueCount} 个原文词。ABA 排名以原表为准，缺值用西柚补齐。西柚 ABA 报告周 ${metricsPeriod} · 父体反查 ${period}`,
    competitors.complete);
  const sortedResult = result
    .sort((left, right) => compareAbaRanks(left[2], right[2]))
    .map((row) => [null, searchUrl(row[0]), ...row]);
  writeTable(resultSheet, 3, 0,
    ["SEARCH", "亚马逊搜索网址", "流量词", "周搜索量", "ABA排名", "西柚点击转化率", ...rankHeaders, "词来源",
      "西柚ABA排名", "指标差异", "西柚ABA报告周"],
    sortedResult, [12, 49, 45, 13, 14, 18, ...rankWidths, 33, 16, 44, 27], "KeywordPool");
  writeSearchLinks(resultSheet, 4, 0, sortedResult.length);
  const competitorStatus = competitors.complete ? "西柚父体反查已完成"
    : competitors.queried ? "已取得部分西柚结果，仍有父体或分页待查询" : "西柚父体反查待查询";
  const competitorSheet = addOutputSheet(competitorBook, competitorSheetName, competitorStatus,
    `美国站 · 父体反查 ${period} · 西柚词指标 ${metricsPeriod}`, competitors.complete);
  const competitorHeaders = ["流量词", ...metricLabels, ...rankHeaders, "命中父ASIN", "指标差异", "西柚ABA报告周"];
  writeTable(competitorSheet, 3, 0, competitorHeaders, competitorRows,
    [45, 13, 16, 18, ...rankWidths, 26, 44, 27], "CompetitorKeywords");
  writeTable(competitorSheet, 3, competitorHeaders.length + 1,
    ["清单 ASIN", "核实父 ASIN", "查询状态", "返回原文词数"], competitors.captureStatus,
    [17, 17, 17, 17]);
  const outputDir = path.dirname(outputPath);
  await fs.mkdir(outputDir, { recursive: true });
  const staging = await fs.mkdtemp(path.join(outputDir, ".keywords-"));
  try {
    let previous = inputPath;
    const attach = fileURLToPath(new URL("./并入词库.py", import.meta.url));
    for (const [index, [book, tab]] of [[competitorBook, competitorSheetName], [resultBook, resultSheetName]].entries()) {
      book.recalculate();
      const donor = path.join(staging, `sheet-${index}.xlsx`);
      const next = path.join(staging, `workbook-${index}.xlsx`);
      await (await SpreadsheetFile.exportXlsx(book)).save(donor);
      await promisify(execFile)(pythonCommand(), [attach, previous, donor, next, "--tab-name", tab]);
      previous = next;
    }
    if (!initialSource.equals(await fs.readFile(inputPath))) {
      throw new Error("源工作簿在生成期间发生变化，请从最新版本重新生成");
    }
    await fs.rename(previous, outputPath);
  } finally {
    await fs.rm(staging, { recursive: true, force: true });
  }
  console.log(`ABA ${abaRowCount} 条、原文去重 ${abaUniqueCount} 个。导入竞品词 ${competitorRows.length} 个，待筛查 ${result.length} 个。`);
  console.log(competitorStatus);
}

if (process.argv[1] && await fs.realpath(process.argv[1]).catch(() => null) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
