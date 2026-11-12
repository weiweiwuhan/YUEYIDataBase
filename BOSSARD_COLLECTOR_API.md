# Bossard 采集工具接口定义

适用版本：独立采集工具2.0（2026-11-12）。这些是**本地命令行和 Python 函数接口**，不是新增的网页 HTTP 接口；无需启动 Web 服务。安装与原理见 [使用教程](BOSSARD_COLLECTOR_GUIDE.md)。

## 1. 配置入口

```text
python run_bossard_collector.py [--config JSON文件] [--mode resume|images-only|export]
```

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--config` | 脚本旁的 `collector_config.json` | UTF-8 JSON 配置文件；相对路径以该文件所在目录为准 |
| `--mode` | `resume` | `resume` 继续属性和主图；`images-only` 只补缓存产品主图；`export` 不联网重新导出 |

运行入口使用当前解释器 `sys.executable`，不会换到另一个 Python 环境。输出为 `output_dir/Bossard_模式_本地时间.xlsx`，每次生成新文件，不传 `--overwrite`。配置字段、默认值、类型和取值范围见教程第4节与代码 `DEFAULT_CONFIG`。

### `load_config(path: Path) -> dict`

读取配置、补齐默认值，校验未知字段、路径类型、布尔值、整数上限和有限数值间隔。成功返回配置字典；配置无效抛 `ValueError`，读文件失败抛 `OSError`。不联网，不创建输出文件。

### `build_command(config: dict, base: Path, mode: str, output: Path) -> list[str]`

输入经过 `load_config` 校验的配置、配置目录、模式和 Excel 输出路径。返回可传给 `subprocess.run` 的参数列表。参数以列表传递，不经过 shell 解析，路径含空格也不会被拆成多条命令。未知模式或补图时关闭下载会抛 `ValueError`。

## 2. 核心采集 CLI

```text
python bossard_catalog.py --categories JSON文件 --output XLSX文件 [其他参数]
```

| 参数 | 默认值/类型 | 行为 |
| --- | --- | --- |
| `--categories` | 必填，文件路径 | 分类数组，或包含 `categories` 数组的 JSON 对象 |
| `--output` | 必填，文件路径 | 审核 XLSX；默认拒绝覆盖已有文件 |
| `--products` | 可选，文件路径 | 从已有产品数组或汇总 JSON 离线导出；汇总含 `categories` 时用其中的最新分类，含 `report` 时保留报告 |
| `--crawl` | 布尔开关 | 启用联网采集；不加时只导出已有输入 |
| `--cache` | `work/bossard-cache` | JSON 断点与 `images/` 所在根目录；包内配置入口会显式改为 `cache` |
| `--delay` | `1.5`秒 | 核心CLI默认间隔；最低1秒，服从更慢的 robots 规则。包内入口默认3秒 |
| `--max-products` | `0` | 非零时限制本轮产品列表条数，包含恢复的缓存；不直接限制分类发现请求数 |
| `--max-category-pages` | `1000` | 本轮分类页面状态上限 |
| `--max-sitemap-pages` | `200` | 本轮公开 sitemap 读取上限 |
| `--browser-executable` | 可选，路径 | 浏览器可执行文件；留空自动寻找系统浏览器或使用已安装的 Playwright Chromium |
| `--skip-images` | 布尔开关 | 不显式下载主图；浏览器仍会正常加载页面资源 |
| `--images-only` | 布尔开关 | 只补已有产品图片；必须有 `--crawl`；不能和 `--skip-images`、`--refresh` 同用 |
| `--image-root` | 可选，路径 | 离线导出时的图片缓存根目录；联网采集时自动采用 `--cache` |
| `--no-embed-images` | 布尔开关 | Excel 只记录路径和来源，不嵌缩略图；不关闭本地图片下载 |
| `--refresh` | 布尔开关 | 重新读取已缓存产品属性页，并重新进行发现；已有断点仍用于恢复已发现链接 |
| `--overwrite` | 布尔开关 | 显式允许覆盖输出文件；不建议用于人工审核表 |

直接 CLI 的相对路径以当前工作目录为准。配置入口会先转换为绝对路径，因此两者使用相对路径的基准不同。

退出码：`0` 程序正常返回，可能仍是部分采集；`1` 采集失败；`2` 访问受限或 argparse 参数错误。运行配置入口自身配置/文件错误返回1。Ctrl+C 是用户中断，不保证当时已经导出最终表，已逐条保存的缓存可续采。

## 3. 采集与导出 Python 接口

### `parse_product(html: str, url: str, category_ids=()) -> dict`

文件：`bossard_catalog.py`。纯解析接口，不发 HTTP 请求。

- `html`：正常渲染后的详情 HTML。
- `url`：实际产品来源地址，必须有 `/p/数字/`。
- `category_ids`：可选分类编号序列。调用方应提供依据，采集主流程会将没有验证依据的分类降为候选。
- 返回：一条 BN 产品系列记录，含技术字段、原始属性、缺失字段及主图候选 URL。
- 失败：正文未确认对应 BN、缺少产品名称或 URL 无 BN 时抛 `ValueError`，不生成假产品记录。

### `PublicCrawler(cache, delay=1.5, max_products=0, max_category_pages=1000, executable=None, max_sitemap_pages=200, download_images=True, images_only=False)`

创建单进程有状态采集器。`cache` 支持字符串或 `Path`；其余参数与 CLI 对应。`executable` 对应 `--browser-executable`。一个缓存目录同时只由一个实例操作。

### `PublicCrawler.crawl(categories: list[dict], refresh=False) -> tuple[list, list, dict]`

输入分类种子，返回 `(分类列表, 产品列表, 采集报告)`。先恢复缓存，再进行发现、属性解析与图片采集。遇网站访问限制，保留成功记录并返回受限报告；`complete_catalog` 不会自动标为完整。`images_only=True` 时不处理新分类或新产品，保留原分类待处理队列。

副作用：写每产品 JSON、分类断点、发现链接、图片和 `crawl-report.json`。**汇总 `export-data.json` 由 CLI 的 `main()` 写出**，直接调用 `crawl()` 的程序如需汇总文件应自行保存返回结果。`images_only=True` 与 `refresh=True` 同时使用会抛 `ValueError`。

### `PublicCrawler.collect_image(page, row: dict) -> None`

给单个产品补图并原地更新 `row`；不返回新字典。`page` 为 Playwright Page；只有旧缓存缺少 `image_url`、需要重读来源页时才需要。已经从 HTML 解析出 URL 时可传 `None`。

照片已经在缓存内时直接跳过。下载前检查 robots、域名和路径，重定向也检查范围。HTTP401/403/429 或 robots 禁止时，记录 `blocked` 并抛 `CrawlBlocked` 供主流程停止；普通网络/图片错误记为 `failed`。无论成功或失败，都会尝试保存当前产品 JSON，保留已成功属性。

### `export_workbook(categories, products, destination, report=None, image_root=None, embed_images=True) -> dict`

离线导出，不联网。`categories/products` 为记录数组；`image_root` 必须是包含 `images/` 的目录，不能直接指向 `images/`。按 BN 数值排序，再将图片锚定到对应数据行。

返回示例：

```json
{"categories":39,"product_series":391,"path":"output/审核.xlsx","embedded_images":1}
```

副作用：创建目标父目录并写 XLSX；所有审核选择重置为“待审核”。**函数自身可覆盖目标文件**，拒绝覆盖是 CLI 的保护；自行调用函数时应先检查目标路径。无效分类树抛 `ValueError`。

### 其他维护接口

| 函数 | 用途 |
| --- | --- |
| `canonical(url)` | 产品页/分类页去追踪参数，保留 page；不可用于图片 |
| `category_paths(categories)` | 构造完整分类路径；拒绝循环或缺失父级 |
| `PublicCrawler.check_robots(url)` | 验证同站URL和 robots；规则不允许时抛 `CrawlBlocked` |
| `PublicCrawler.cache_path(url)` | 返回来源 URL 的 SHA-256 命名 JSON 路径 |
| `PublicCrawler.write_json(path, value)` | 临时文件写入后替换；不提供多进程锁 |
| `PublicCrawler.needs_image(row)` | 根据下载开关和本地图片是否存在决定是否补图 |

## 4. 图片模块接口

文件：`bossard_images.py`。模块本身不发请求，便于离线测试和复用。

| 接口 | 输入与返回 |
| --- | --- |
| `allowed_image_url(url: str) -> bool` | 仅允许 Bossard 中国站 HTTPS、默认/443端口、无账号信息的 `/eshopmedia/` 或 `/medias/` 路径 |
| `image_url(value, page_url) -> str` | 将相对图片地址转绝对地址，保留媒体参数；不允许的地址返回空字符串 |
| `select_product_image(doc, page_url) -> dict` | `doc` 为 lxml HTML；返回主图 URL、选取依据、状态和说明；找不到时状态 `not_found` |
| `save_product_image(cache, row, content: bytes) -> None` | 校验实际图片、保存原文件和PNG，原地更新记录。无效BN、超限和坏图抛异常 |
| `local_image(root, row) -> Path\|None` | 只解析缓存根目录内的已有文件，越界/缺失返回None |
| `add_workbook_images(sheet, products, image_column, image_root, embed=True) -> int` | 按产品行顺序添加缩略图，返回实际嵌图数；列号从1开始，产品数组顺序必须与工作表一致 |

图片最多15 MiB、2000万像素。支持 Pillow 能实际识别的 JPEG、PNG、WebP、GIF、BMP、TIFF；GIF/TIFF 的查看 PNG 使用首帧。文件名从已验证的 BN 生成，不接受网页提供任意保存路径。

原始文件保留 HTTP 响应字节，PNG 保留图片内容和可用透明度。Excel 缩略图以白色衬底显示，最大140×105像素，行高86磅，原图尺寸另存记录。缩略图是 Excel 浮动对象，不是公式或网络外链。

## 5. JSON 数据约定

分类输入：

```json
{"categories":[{"category_id":"01.100","parent_id":null,"name":"标准紧固件","source_url":"https://www.bossard.com.cn/cn-zh-cn/eshop/products/fastening-technology/standard-fastening-elements/c/01.100/"}]}
```

`cache/export-data.json` 的结构：

```text
{
  "categories": [分类记录, ...],
  "products": [产品系列记录, ...],
  "report": {本轮采集报告}
}
```

产品主要字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `source_system` | string | 当前为 `bossard_cn` |
| `source_product_id` | string | 稳定 BN 键，例如 `BN2` |
| `bn` | string | 展示编号，例如 `BN 2` |
| `record_scope` | string | `series`，不是具体尺寸SKU |
| `name` / `source_url` / `fetched_at` | string | 产品名称、来源页、UTC ISO8601采集时间 |
| `head_type` / `drive_type` / `thread_type` | string | 头型、驱动槽型、螺纹，缺失为空字符串 |
| `material` / `material_type` / `manufacturing_material` | string | 材质、材料类型、制造材料，分别保存 |
| `property_class` / `surface_treatment` / `color` / `standards` | string | 性能等级、处理、颜色、标准原值 |
| `raw_attributes` | object | 来源页原始属性名与值 |
| `field_sources` | object | 技术字段对应的原站标签 |
| `missing_fields` | string[] | 未可靠获取的技术字段名 |
| `category_ids` | string[] | 已确认分类；未确认时留空 |
| `category_candidates` | object[] | 候选分类、来源和证据，需人工核实 |
| `review_status` / `import_approved` | string / boolean | 采集主流程设“待审核”/false，不能自动导入 |
| `image_url` | string | 所选主图的实际媒体URL，找不到时为空 |
| `image_evidence` | string | 主画廊标记或可靠缩略图的选取依据 |
| `image_status` | string | 下表中的状态；旧缓存没有该字段时按待补图处理 |
| `image_note` | string | 缺图或失败原因；成功时为空 |
| `image_path` | string，可缺省 | PNG副本相对缓存根目录的路径，如 `images/BN2.png` |
| `image_original_path` | string，可缺省 | 原始响应文件路径，如 `images/BN2.source.webp` |
| `image_sha256` | string，可缺省 | 原始响应字节的SHA-256，64位十六进制 |
| `image_width` / `image_height` | integer，可缺省 | 所选图片实际像素尺寸 |
| `image_fetched_at` | string，可缺省 | 图片成功下载时间，UTC ISO8601 |

| 图片状态 | 意义 |
| --- | --- |
| `pending` | 已定位 URL，尚未下载；也用作旧缓存的缺省显示 |
| `downloaded` | 下载成功并保存原始文件和PNG。报告同时检查当前PNG是否仍存在，不能只看历史状态 |
| `not_found` | 页面没有可确认的产品照片 |
| `failed` | 下载、格式校验或解析失败，错误保留 |
| `blocked` | 访问受限，主流程停止并保留现有数据 |

图片状态和审核状态是两回事：有照片不代表记录已经审核通过。

## 6. 报告字段与文件关系

| 报告字段 | 意义 |
| --- | --- |
| `status` | 本轮返回状态，可能是部分采集、受限或失败 |
| `complete_catalog` | 当前始终false，不自动宣称完整目录 |
| `discovered_unique_bn_count` | 真正发现过的唯一BN数 |
| `exported_product_series` | 本轮成功恢复/解析并返回的产品数 |
| `pending_product_ids` | 已发现但尚未成功解析的BN |
| `download_images` / `images_only` | 本次运行的图片选项 |
| `downloaded_image_count` | 对已返回产品检查，本地PNG实际存在的数量 |
| `image_status_counts` | 产品记录中的图片状态分布；历史 downloaded 但文件丢失时可能与实际数不同 |
| `pending_image_ids` | 已返回产品中本地PNG缺失的BN，不包含还没成功取得属性的产品 |
| `remaining_category_urls` / `pending_sitemaps` | 待处理分类与 sitemap |
| `pagination_unverified` | 分页未确认或未推进的记录 |
| `failed_or_unverified` | 失败 URL、阶段与原因；图片阶段为 `product_image` |
| `completed_at` | 本轮报告结束时间，UTC ISO8601 |

导出 Excel 的返回值另有 `embedded_images`，“采集报告”工作表另加 `embedded_image_count`，表示这份 Excel 实际嵌入的缩略图数；关闭嵌图时为0，不能据此认为本地没有图片。

## 7. 小例子：只测试解析与导出

下面不访问源站，适合学习接口；`page.html` 是自行保存的已渲染产品HTML。先用真实来源地址校验BN，再导出一行待审核记录：

```python
from pathlib import Path
from bossard_catalog import parse_product, export_workbook

url = "https://www.bossard.com.cn/cn-zh-cn/eshop/screws-and-bolts-with-internal-drive/hex-socket-head-cap-screws-partially-threaded/p/2/"
row = parse_product(Path("page.html").read_text(encoding="utf-8"), url)
print(row["name"], row["image_url"])

# 示例仅生成无分类的一行工作簿；正式采集沿用包内分类与断点。
export_workbook([], [row], "单条解析测试.xlsx", image_root="cache")
```

若要直接下载已定位的图片，可以在允许访问源站的网络中调用 `PublicCrawler("cache", delay=3).collect_image(None, row)`。它仍检查 robots 与访问范围；这一步会联网。正式批量操作建议用配置入口，避免遗漏报告、断点恢复和退出码处理。
