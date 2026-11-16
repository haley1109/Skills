---
name: listing-look-and-understand
description: "listing查看和理解 —— 用户发来亚马逊链接或 ASIN 时，像人一样浏览整条 listing（父体 + 全部子体）：自动设美国邮编、用 Edge/Selenium 实渲染、解析标题/品牌/类目/五点/A+/详情/评论/价格/库存/变体结构，输出整条链接的综合理解与诊断。当用户说『看看这个链接/这个 ASIN/帮我理解这个 listing/抓变体/listing查看』时使用。"
---

# listing 查看和理解（listing-look-and-understand）

## 何时用
用户给出一条亚马逊链接或一个 ASIN，要求「理解这个产品 / 看看这个 listing / 抓所有变体 / 分析这个页面」。
**默认要把整条链接（父体 + 全部子体 ASIN）都抓一遍**；只有用户明确说「只看某一个 ASIN」时才只抓那一个。

## 核心前提（必须满足，否则渲染必失败）
1. **会话必须是 `danger-full-access` 文件/进程策略**。在 `workspace-write` 沙箱下，Edge 的多进程渲染被 named pipe 限制卡死，`--dump-dom`/截图/PDF **全部 0 字节**，只有 `msedge --version` 能出。切到 full-access 后实测可渲染（`LEN ~1.1M`）。
2. **用 Selenium WebDriver，不要用 `--dump-dom`**。Edge 157（Chromium 157）的新无头对 `--dump-dom` 不兼容，会报 `Multiple targets are not supported in headless mode` 或静默 0 字节。Selenium 走 WebDriver 协议，稳定拿到 `page_source`。
3. **系统 python 已装 selenium + lxml**（`python -m pip install selenium lxml`）。MS Edge 已安装（`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`）。注意：selenium 用于抓取、lxml 用于解析；自带 python 有 lxml 但没 selenium，系统 python 反之，所以两个都要装进系统 python。
4. **必须先设美国邮编 20003**。否则 Amazon 按默认发货地（中国）显示「Deliver to China / cannot be shipped」，**价格被隐藏**、页面显示「Currently unavailable」假象。zip 通过 glow 接口 POST 设置即可。

## 一键流程（在工作区目录下执行）
```powershell
Set-Location <工作区>
# 1) 抓整条链接：设邮编 -> 解析 dimensionValuesDisplayData 得到全部子体 -> 逐个抓 DOM + 顶部截图
python <skill>\scripts\capture_all_variants.py <父体ASIN> 20003
# 2) 解析父体/单页 -> page_content.md（标题/品牌/类目/价格/评分/五点/描述/A+/详情/变体）
python <skill>\scripts\extract_page.py product_pages\<ASIN>\page.html
# 3) 生成 6 子体对比表 -> variants_summary.md（价格/库存/评分/主图/配送）
python <skill>\scripts\summarize_variants.py product_pages <父体ASIN>
# 4) 导出每个子体的标题+五点原文 -> bullets_by_variant.txt
python <skill>\scripts\bullets_by_variant.py product_pages <父体ASIN>
# 5) 逐子体差异比对（标题/五点/规格词）-> variant_diff.md（必做！）
python <skill>\scripts\variant_diff.py product_pages <父体ASIN>
```

> **重要**：`page_content.md` 只反映你传入的那个 ASIN 的单页内容，**不代表整条链接**。整条链接的差异必须看 `variant_diff.md`。
单页模式（只想看一个 ASIN）：`python <skill>\scripts\capture_single.py <ASIN> 20003`

输出统一落在 `<工作区>\product_pages\<ASIN>\`：`page.html`（实渲染 DOM）、`page_top.png`、`children.json`、`variants_summary.md`、`bullets_by_variant.txt`。
随后用 `read` 读这些文件、用 `read_image` 读 `page_top.png` 做视觉确认，最后综合成 `listing_overview.md`。

## 关键解析节点（Amazon 新版页面结构，别用旧选择器）
- **标题**：`//*[@id='productTitle']`（注意：不含品牌前缀/尺码）
- **品牌**：`//*[@id='bylineInfo']`
- **类目面包屑**：`//*[@id='wayfinding-breadcrumbs_feature_div']//a`
- **五点（About this item）**：新版在 `<h3 class="product-facts-title">About this item</h3>` 后的 `<ul><li><span class="a-list-item">`，**不是**旧的 `#feature-bullets`
- **A+**：`#aplus`（需排除 `<style>/<script>` 文本；常是图片+少量文字）
- **价格**：`#corePrice_feature_div` / `#corePriceDisplay_desktop_feature_div` / `#buybox` 的 `.a-offscreen`
- **库存**：`#availability`（要剔除内嵌 script 文本）
- **变体结构**：父页里的 `dimensionValuesDisplayData` JSON = `{子体ASIN: [值1, 值2, ...]}`；**维度顺序不固定**（可能是 `[color,size]` 也可能是 `[size,color]`），必须用页面里的 `sortedDimValuesForAllDims`（`{size_name:[{dimensionValueDisplayText:...}]}`）把每个值映射回正确维度名，不要按固定位置假设；`variationDisplayLabels` 是维度名→显示名的映射。
- **主图**：`#landingImage` 的 `data-a-dynamic-image`（JSON，取最大宽高 URL），退化取 `src`

## 踩过的坑（务必记住）
1. **`Number of Items` 可能是「件数配置」而不是「多件装」**：本案例 1=睡裙单件、2=睡裙+睡袍套装，两套五点文案完全不同、价格差 $12。逐子体抓才能发现。
2. **`Color` 可能只有 1 个值**（伪维度），别当成真实变体。
3. **父体 ASIN 可能不在 `dimensionValuesDisplayData` 里**：它是虚拟父体，`/dp/父体` 默认显示某个子体。
4. **标题、五点、规格词都可能逐子体不同，禁止假设共享**：常见形态是「单件标题无 Set / 多件标题带 Set of N」、单件与多件用**两套不同五点模板**、甚至同尺寸同件数却混用不同模板（本案例 B0H5QP6HXS 18x18/2 标题写 Set of 2 但五点用了单件 450g 模板）。**必须跑 `variant_diff.py` 逐子体比对**，用 `page_content.md` 下结论前先确认它是哪个 ASIN。
5. 抓取会话默认发货地可能不是美国（按 IP/语言），**不设邮编就会误判为不可售/无价格**。
6. **五点分组前会归一化大小写与句末标点**：否则「多一个句号」就会被误报成两组（本案例 B0GPQDS6P5 的 Black 就是这样假异常）。报告前先确认差异是否为实质内容。

## 边界情况（已实测）
- **单变体（无 twister / 无 `dimensionValuesDisplayData`）**：children 为空时自动把目标 ASIN 当作唯一变体抓取；矩阵输出 `PRICE_MATRIX: n/a`。
- **只有 1 个维度在变**（如 36 色的假发）：输出 `PRICE_LIST (by Color)`，**不要**退化成 X×X 对角线。
- **2 个维度在变**：输出 `PRICE_MATRIX`（自动选取值最多的两维）。
- **coupon / 促销**：`extract_page.py` 输出 `## Coupon / Promo`（实测能抓到 "Save 20% with coupon / You pay $xx"）。
- **非标准尺寸字符串**（`50x70cm`、`10 inch (Pack of 1)`）：按字符串处理，维度映射与矩阵照常工作。
- **children.json 可能带 BOM**：所有读取用 `utf-8-sig`，用记事本改过也能读。
- **品牌**：`#bylineInfo` 缺失时回退到 `th[Brand*]/td` 与详情列表；极个别 listing 可能仍为空。

## 交付物
- `listing_overview.md`：整条链接（父+子）综合理解（结构/价格/库存/评论/变体矩阵/诊断与机会）
- 各子体 `page.html` + `page_top.png`
- 若有矛盾（如 A+ 展示袍子但单件不含袍、套装共用单件标题），必须点出并给优化建议

## 降级方案（若无法获得 full-access）
让用户在自己终端双击/运行抓取脚本（同一 `capture_all_variants.py`），抓完把 `product_pages` 放回工作区，再执行第 2~4 步解析。
