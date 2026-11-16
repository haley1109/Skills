# listing-look-and-understand 1.1.1

2026-11-16 修订。保留父子体、标题、五点、Description、A+、主商品价格、库存、评价汇总、图片与逐子体差异分析。原六个命令入口仍可用，抓取与解析改为共享模块。1.1.1 修复整组抓取时请求子体截图可能被相邻子体覆盖的问题。

## 安装依赖

需要 Python 3.10+。建议在虚拟环境中安装。离线解析只需 lxml，在线抓取另需 Selenium 和已安装的兼容浏览器。

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-online.txt
.venv\Scripts\python scripts/capture_single.py --diagnose
```

也可 `powershell -NoProfile -File install.ps1`；仅离线依赖用 `-Offline`。无需关闭保护或修改执行策略。

Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-online.txt
.venv/bin/python scripts/capture_single.py --diagnose
```

也可 `sh install.sh` 或 `sh install.sh --offline`。离线环境如没有依赖，可在允许联网、相同平台/Python 的环境准备 wheel，再用 pip 的 `--no-index --find-links` 安装；安装依赖不会解除网络限制。

`requirements.txt`：lxml >=5.3,<7；`requirements-online.txt`：再加 selenium >=4.26,<5。此次实际测试版本为 Python 3.12.10、lxml 6.1.3、Selenium 4.52.0。没有承诺所有允许版本和操作系统都已实机测试。

## 在线读取

下列命令在希望保存结果的工作区执行；将 `<skill>` 替换为 Skill 绝对路径。路径有空格时加引号。

```text
python <skill>/scripts/capture_all_variants.py B0H4VBC1SD 20003 --output product_pages
python <skill>/scripts/analyze_listing.py product_pages B0H4VBC1SD
```

仅抓一页：

```text
python <skill>/scripts/capture_single.py B0H4VBC1SD 20003 --output product_pages
```

`B0H4VBC1SD` 是待抓取目标示例，不表示已成功访问。自动选择 Windows Edge；Linux 优先检测 Chrome/Chromium，也可显式指定：

```text
python <skill>/scripts/capture_all_variants.py B0H4VBC1SD --browser chrome --binary /usr/bin/chromium --driver /usr/bin/chromedriver
python <skill>/scripts/capture_single.py B0H4VBC1SD --browser edge --driver C:/drivers/msedgedriver.exe
```

自动检测还支持 PATH 中的浏览器/驱动，以及 Windows 的 Program Files / LocalAppData 常用路径。未指定驱动且 PATH 没有驱动时，Selenium Manager 可能需要联网解析和下载驱动；失败会报告 DRIVER_UNAVAILABLE。受限环境请提供与浏览器版本兼容的本地驱动。不会自动安装浏览器。

默认 headless；`--headed` 可显示独立临时浏览器。不会接入现有个人登录配置。`--timeout 25` 控制页面/脚本等待，`--delay 1.5` 控制子体间隔；驱动管理器的连接超时由其自身配置控制。Linux 需要正常可运行的 Chrome/Chromium 及系统库；容器若不允许浏览器运行，改用离线模式。脚本不禁用浏览器安全保护。

邮编默认 20003，可按用户指定更换。脚本发送配送地区请求并重载页面，仅当页面配送文字实际显示目标邮编时记录 `delivery_zip_verified=true`。失败会保留警告，不把价格或无货状态当成已验证的美国配送结论。

## 离线 HTML 导入

在允许访问 Amazon 的浏览器打开目标和各子体，确认所选规格、地区及 A+ 内容已加载后保存 HTML。建议一页一个文件。保存为 PDF、截图或仅复制正文不能供 HTML 解析器使用；图片可供 AI 辅助查看。HTML 可能含个人配送信息，请仅提供必要页面。

单页：

```text
python <skill>/scripts/import_html.py B0H4VBC1SD --html saved-page.html --output product_pages
```

多页：

```text
python <skill>/scripts/import_html.py B0H4VBC1SD --html-dir saved_pages --output product_pages
python <skill>/scripts/analyze_listing.py product_pages B0H4VBC1SD
```

目录支持 `<ASIN>.html` 或 `<ASIN>/page.html`。优先读取 DOM 中所选 ASIN，其次 canonical URL；缺少身份信息时文件名只作未核实标签。导入父体时可用页面中 parentAsin 关联其默认子体。只提供一页不会生成其他子体的内容；缺失子体出现在 coverage.missing 中。离线模式不导入 Selenium、不启动浏览器、不访问网络。

同一 ASIN 有不同快照时报告 DUPLICATE_ASIN，不悄悄选择较新版本。快照时间、库存实时性及配送地区未核验；不得当作在线实时抓取结果。

## 报告与旧命令兼容

```text
python <skill>/scripts/extract_page.py product_pages/<ASIN>/page.html
python <skill>/scripts/summarize_variants.py product_pages <目标ASIN>
python <skill>/scripts/bullets_by_variant.py product_pages <目标ASIN>
python <skill>/scripts/variant_diff.py product_pages <目标ASIN>
```

`analyze_listing.py` 一次执行以上报告功能，为每个有效子体生成 page_content.md/json，并生成 listing_overview.md 证据索引。旧模式只生成其对应报告。

每页目录：page.html、capture.json、page_content.md/json；在线可有 page_top.png。目标目录：children.json、run.json、diagnostics.json、variants_summary.md、bullets_by_variant.txt、variant_diff.md、listing_overview.md。仅 extract_page.py 不需要 children.json。

run.json 记录入口 ASIN、页面披露父体、本次采集页面、来源、时间、浏览器、配送核验、覆盖率、错误与警告；capture.json 记录所选 ASIN 与 HTML 校验值。重复运行后报告只读取本次成功页面，过期文件保留但不会自动拿来补齐。旧目录无 run.json 时仍可解析，会标为 legacy/untracked。

价格仅取主商品区域；优惠文本单列。不把推荐商品或划线原价当成交价。无价格/无 A+ 文本均保持 unknown。A+ 文字和图片地址保留，图片内容需视觉确认。不会根据脚本结果推断材质、洗护或生成用户直评。

维度按页面值集合匹配，不固定顺序；匹配不唯一保留 unmapped。一维生成 PRICE_LIST，二维及更多维生成 PRICE_MATRIX，同格多个 ASIN 全部保留，避免第三维被覆盖。Number of Items 不自动解释成多件装。

## 错误与降级

| 代码 | 含义与下一步 |
|---|---|
| DEPENDENCY_MISSING | 按离线/在线模式安装相应依赖 |
| BROWSER_MISSING | 指定已安装浏览器 `--binary`，或使用离线 HTML |
| DRIVER_UNAVAILABLE | 检查本地驱动版本/路径，允许时正常下载匹配驱动；受限则离线 |
| BROWSER_START_OR_RUNTIME_FAILED | 查看具体错误，检查系统库与宿主执行能力；不要关闭保护 |
| NETWORK_POLICY_BLOCKED | 明确的管理员网络阻拦；停止在线尝试，使用授权保存的 HTML |
| NETWORK_ERROR / NETWORK_BLOCKED | 连接、DNS、代理、证书错误或拒绝页；按具体原因修复正常访问或离线导入 |
| CAPTCHA / LOGIN_REQUIRED | 当前是验证/登录页，未取得商品页；由用户在正常浏览器处理后保存 HTML |
| PAGE_TIMEOUT | 页面/脚本等待超时；未证明 Amazon 不存在或永久不可访问 |
| EMPTY_HTML / NOT_PRODUCT_PAGE / PARSE_FAILED | 空文件、未含商品标题、结构变化或不完整页面；检查原文件 |
| ASIN_MISMATCH / TARGET_NOT_FOUND | 文件标记或重定向与目标不符；不得把另一页冒充目标 |
| SNAPSHOT_CHANGED | 文件不再匹配本次记录的校验值，重新导入或采集 |
| NO_HTML_FILES / FILE_ERROR | 检查输入目录、编码与输出权限 |

抓取/导入进程退出码：0=已发现集合成功（仍需看警告），2=失败，3=部分覆盖/存在导入错误；参数错误为 2。报告命令 0 仅证明生成了文件。不要把 shell 包装层显示的退出码或“报告已写入”当成 Amazon 成功访问证据，查看 run.json。

## 测试

```text
python -m unittest discover -s tests -v
```

测试使用 B000000000 等合成 ASIN。包含页面有效性、父体重定向、价格范围、A+、新旧五点、JSON 字符串转义、非标准尺寸、歧义维度、部分覆盖、旧文件隔离、校验变化、BOM、纯离线无网络执行、平台选择，以及目标子体截图不被兄弟子体覆盖。平台选择模拟测试不等于 Linux 实机验证；测试通过不表示已抓到真实 ASIN。

## 在其他 Agent 宿主中使用
将此目录作为独立 Skill 安装。需要 Python 3.10+；离线解析需 lxml，在线抓取还需要 Selenium、已安装的兼容浏览器及宿主允许浏览器自动化。安装 Skill 不会转移浏览器、网络权限、账号登录状态或验证码访问能力。

## 官方实现参考

2026-11-16 核对：[Selenium Edge](https://www.selenium.dev/documentation/webdriver/browsers/edge/)、[Selenium Chrome](https://www.selenium.dev/documentation/webdriver/browsers/chrome/)、[Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/)。脚本使用浏览器 Options 的 binary_location 和 Service 的 executable_path；Manager 仅作为未指定本地驱动时的常规驱动管理后备。


