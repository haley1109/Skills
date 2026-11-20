import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { loadArtifact, pythonCommand } from "./runtime.mjs";
import { writeTable } from "./合并词库.mjs";

const help = `用法：node 否词表.mjs <含词库页的完整操作表.xlsx> <逐词归因.json> <完整输出.xlsx>
将「否词表」加入当前操作表；已有该页时请选用加页前的版本。
归因文件示例（实际项目需覆盖每一条不相关原词）：
{
  "protected": ["pillow cover", "linen"],
  "roots": [{"root":"velvet", "category":"材质", "reason":"商品为亚麻面料，搜索词指定丝绒。", "variants":[], "contextOnly":false}],
  "rows": [
    {"keyword":"velvet pillow cover", "roots":["velvet"]},
    {"keyword":"pillow cover", "roots":[], "review":"整词复核", "note":"该词是品类核心词。"}
  ]
}
protected 包含本次产品、变体的核心词与适配属性；variants 可选，列出复数、异拼、其他语言等已核对的等价形式。contextOnly 可选，用于多义或特定组合。每条归因的词根或变体须实际出现在原词。没有可归因属性时填「整词复核」或「词义待核对」并给出说明。程序从工作簿读取原评级、依据、译文和行号，对相关及强相关原词检查命中并限制适用范围。`;

const run = promisify(execFile);
const readSource = `
import json, sys
from openpyxl import load_workbook
book = load_workbook(sys.argv[1], read_only=True, data_only=True)
required = ['流量词', '中文翻译', '相关性', '相关性依据']
try:
    if '否词表' in book.sheetnames:
        sys.exit('输入已有「否词表」，请选用加页前的版本')
    sheet = book['词库']
    columns = None
    rows = []
    for n, row in enumerate(sheet.values, 1):
        if columns is None:
            if all(label in row for label in required):
                columns = [row.index(label) for label in required]
            continue
        cells = [row[i] for i in columns]
        if all(value is None for value in cells):
            continue
        rows.append([n] + cells)
    if columns is None:
        sys.exit('词库缺少必需的列：' + '、'.join(required))
    print(json.dumps(rows, ensure_ascii=True))
finally:
    book.close()
`;

function nonempty(value) { return typeof value === 'string' && value.trim().length > 0; }
const tokens = (s) => s.normalize('NFKC').toLowerCase().match(/[\p{L}\p{M}\p{N}]+/gu) ?? [];
const phrase = (s) => tokens(s).join(' ');
const contains = (haystack, needle) => ` ${haystack} `.includes(` ${needle} `);

// Conservative English noun plural handling applies only to the collision check.
// Explicit variants handle irregular plurals and other languages.
function possibleBases(token) {
  const result = new Set([token]);
  if (!/^[a-z]{3,}s$/.test(token) || token.endsWith('ss')) return result;
  result.add(token.slice(0, -1));
  if (/(sh|ch|ss|x|z|o)es$/.test(token)) result.add(token.slice(0, -2));
  if (/ies$/.test(token)) result.add(token.slice(0, -3) + 'y');
  return result;
}

function collides(query, root) {
  return query.some((_, start) => start + root.length <= query.length && root.every((bases, i) => {
    for (const base of bases) if (query[start + i].has(base)) return true;
    return false;
  }));
}
const collisionTokens = (text) => tokens(text).map(possibleBases);

function build(source, data) {
  const protectedWords = data?.protected;
  if (!Array.isArray(protectedWords) || !Array.isArray(data.roots) || !Array.isArray(data.rows)) {
    throw new Error('归因文件须含 protected、roots、rows 三个数组');
  }
  if (protectedWords.some(s => !nonempty(s) || !phrase(s))) throw new Error('保护词为空或无有效字符');
  const protectedTokens = protectedWords.map(collisionTokens);
  const index = new Map();
  const seenForms = new Set();
  for (const def of data.roots) {
    const {root, category, reason, variants = [], contextOnly = false} = def;
    if (![root, category, reason].every(nonempty) || !Array.isArray(variants) || typeof contextOnly !== 'boolean') {
      throw new Error(`词根定义不完整：${root}`);
    }
    const names = [root, ...variants];
    if (names.some(v => !nonempty(v) || !phrase(v))) throw new Error(`词根或其变体为空：${root}`);
    const forms = [...new Set(names.map(phrase))];
    if (forms.some(form => seenForms.has(form))) throw new Error(`词根定义或其变体重复：${root}`);
    const scanners = forms.map(collisionTokens);
    if (scanners.some(form => protectedTokens.some(p => p.length === form.length && collides(p, form)))) {
      throw new Error(`归因命中保护词，请结合更具体的属性或保留整词复核：${root}`);
    }
    forms.forEach(f => seenForms.add(f));
    index.set(root, {root, category, reason, forms, scanners, contextOnly, negatives:[], positives:[]});
  }

  const notes = new Map();
  for (const row of data.rows) {
    if (!nonempty(row.keyword) || notes.has(row.keyword) || !Array.isArray(row.roots) || new Set(row.roots).size !== row.roots.length) {
      throw new Error(`归因原词为空、重复或 roots 格式有误：${row.keyword}`);
    }
    if (!row.roots.length && (!['整词复核','词义待核对'].includes(row.review) || !nonempty(row.note))) {
      throw new Error(`缺少整词复核状态或说明：${row.keyword}`);
    }
    notes.set(row.keyword, row);
  }

  const seen = new Set();
  const detail = [];
  const positives = [];
  for (const [n, keyword, translation, grade, basis] of source) {
    if (![keyword, translation, basis].every(nonempty) || seen.has(keyword) || !['强相关','相关','不相关'].includes(grade)) {
      throw new Error(`词库第 ${n} 行的关键词、翻译、评级或依据需核对`);
    }
    seen.add(keyword);
    if (grade !== '不相关') {
      positives.push({keyword, parts:collisionTokens(keyword)});
      continue;
    }
    const row = notes.get(keyword);
    if (!row) throw new Error(`漏掉不相关原词（词库第 ${n} 行）：${keyword}`);
    notes.delete(keyword);
    const normalized = phrase(keyword);
    for (const root of row.roots) {
      const def = index.get(root);
      if (!def || !def.forms.some(form => contains(normalized, form))) {
        throw new Error(`词根未定义或与原词没有连续文字对应：${root} / ${keyword}`);
      }
      def.negatives.push(keyword);
    }
    detail.push({row, n, translation, basis});
  }
  if (notes.size) throw new Error(`归因文件含本轮不相关列表以外的原词：${notes.keys().next().value}`);
  for (const def of index.values()) {
    if (!def.negatives.length) throw new Error(`词根缺少归因原词：${def.root}`);
    def.positives = positives.filter(p => def.scanners.some(s => collides(p.parts, s))).map(p => p.keyword);
    def.restricted = def.contextOnly || def.positives.length > 0;
  }
  const roots = [...index.values()].sort((a, b) => Number(a.restricted) - Number(b.restricted) ||
    b.negatives.length - a.negatives.length || a.root.localeCompare(b.root));
  const rootRows = roots.map(d => [d.root,d.category,d.negatives.length,d.positives.length,
    d.restricted ? '限原词组合' : '可提取为词根',d.reason,d.negatives.slice(0, 2).join(' ｜ '),d.positives.slice(0, 2).join(' ｜ ') || null]);
  const detailRows = detail.map(({row,n,translation,basis}) => {
    const scope = row.roots.some(root => !index.get(root).restricted) ? '可归因' : '限原词组合';
    return [row.keyword,translation,row.roots.join(' ｜ ') || null,row.roots.length ? scope : row.review,basis,n,row.note ?? null];
  });
  return {roots:rootRows, detail:detailRows, mapped:detail.filter(({row}) => row.roots.length).length};
}

function author(book, data) {
  const sheet = book.worksheets.add('否词表');
  sheet.showGridLines = false;
  sheet.tabColor = '#16495B';
  sheet.getRange('A1').values = [['否词表']];
  sheet.getRange('J1').values = [['原词归因明细']];
  for (const cell of ['A1', 'J1']) sheet.getRange(cell).format.font = {name:'Aptos', size:17, bold:true, color:'#16495B'};
  sheet.getRange('A2:D2').values = [[`不相关词 ${data.detail.length}`, `可归因 ${data.mapped}`, `需复核 ${data.detail.length - data.mapped}`, `属性词根 ${data.roots.length}`]];
  sheet.getRange('F3').values = [['限原词组合包含命中相关词或依赖语境的属性。']];
  sheet.getRange('J3').values = [['词库行号对应原表。']];
  sheet.getRange('A1').format.rowHeight = 29;
  sheet.getRange('A2:A3').format.rowHeight = 21;
  sheet.getRange('I1').format.columnWidth = 4;
  sheet.freezePanes.freezeRows(4);
  writeTable(sheet,3,0,['否定属性词根','所属属性','归因不相关原词数','命中相关原词数','适用范围','不匹配原因','不相关原词示例','相关原词示例'],
    data.roots,[25,16,18,17,20,48,43,42],'NegativeRootList');
  writeTable(sheet,3,9,['不相关流量词','中文翻译','归因词根','处理状态','相关性依据','词库行号','说明'],
    data.detail,[42,30,33,18,25,12,57],'NegativeAttribution');
  if (data.roots.length) {
    const end = data.roots.length + 4;
    sheet.getRange(`F5:H${end}`).format.wrapText = true;
    sheet.getRange(`E5:E${end}`).conditionalFormats.addCustom('=E5="限原词组合"',{fill:'#FFF2CC',font:{color:'#65440D',bold:true}});
  }
  if (data.detail.length) {
    const end = data.detail.length + 4;
    sheet.getRange(`A5:P${end}`).format.verticalAlignment = 'center';
    sheet.getRange(`A5:A${end}`).format.rowHeight = 34;
    sheet.getRange(`L5:L${end}`).format.wrapText = true;
    sheet.getRange(`P5:P${end}`).format.wrapText = true;
  }
}

async function main(args) {
  if (args.length === 1 && ['-h','--help'].includes(args[0])) { console.log(help); return; }
  if (args.length !== 3) throw new Error(help);
  const [sourceFile, jsonFile, outputFile] = args.map(p => path.resolve(p));
  const python = pythonCommand();
  const sourceBytes = await fs.readFile(sourceFile);
  const {stdout} = await run(python,['-c',readSource,sourceFile],{maxBuffer:128*1024*1024,encoding:'utf8'});
  const data = build(JSON.parse(stdout),JSON.parse(await fs.readFile(jsonFile,'utf8')));
  const {Workbook, SpreadsheetFile} = await loadArtifact();
  const book = Workbook.create();
  author(book, data);
  await fs.mkdir(path.dirname(outputFile),{recursive:true});
  const staging = await fs.mkdtemp(path.join(path.dirname(outputFile),'.keyword-negatives-'));
  try {
    const donor = path.join(staging,'sheet.xlsx');
    const combined = path.join(staging,'workbook.xlsx');
    await (await SpreadsheetFile.exportXlsx(book)).save(donor);
    const merger = fileURLToPath(new URL('./并入词库.py',import.meta.url));
    await run(python,[merger,sourceFile,donor,combined,'--tab-name','否词表']);
    if (!sourceBytes.equals(await fs.readFile(sourceFile))) throw new Error('源操作表已更新，请用最新版本重新生成');
    await fs.rename(combined,outputFile);
  } finally { await fs.rm(staging,{recursive:true,force:true}); }
  console.log(`否词表已并入。覆盖 ${data.detail.length} 个不相关原词，${data.mapped} 词可归因，共 ${data.roots.length} 个属性词根。`);
}
main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
