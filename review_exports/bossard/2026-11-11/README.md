# Bossard 审核文件与本地采集工具

独立工具包已更新至 **2.0（2026-11-12）**：新增主产品照片下载、Excel“产品图片”列、只补图片模式、JSON参数配置、Windows入口和详细注释/接口教程。

元数据仍沿用2026-11-11快照：39个分类节点、391个已解析BN系列，另有317个BN待续采。前轮遇HTTP403停止，尚未完成全量；分类归属仅为候选，需人工核实。BN2主图已完成实际下载验证并随包提供，其余390个已解析产品的照片需要在本地补采。文件不会自动导入业务库，图片也不会经Excel自动进入业务图片库。

## 下载

- **[新版采集工具包：产品图片、缓存、配置与教程](Bossard_collector_with_product_images.zip)**
- [审核 Excel：391个BN，新增产品图片等辅助列](Bossard_review_391_BN.xlsx)
- [317个待续采BN清单](pending_317_BN.csv)
- [原工具包下载入口](Bossard_review_and_resume_tools.zip)也已同步为新版内容。

点击文件名进入 GitHub 文件页，再点右上角的 **Download raw file（下载原始文件）** 图标。若需要登录，请使用有仓库权限的GitHub账号。无需使用聊天右侧Workspace的下载按钮。

也可本地执行 `git pull`，到 `review_exports/bossard/2026-11-11/` 取文件；或在仓库首页使用 **Code → Download ZIP** 下载整个仓库再解压。

## 本地怎么用

1. **完整解压**工具包到可写目录。
2. 打开 `settings.bat`，将 `COLLECTOR_PYTHON` 改为本机 Python3.10+ 的命令或完整路径。
3. 双击 `01_install.bat` 安装依赖与浏览器。
4. 先运行 `03_images_only.bat` 为缓存产品补照片；继续采集其余产品时运行 `02_resume_with_images.bat`。
5. 日常参数改 `collector_config.json`。Excel保存在 `output/`，图片原文件和PNG保存在 `cache/images/`；`04_export_offline.bat` 可不联网重新导出。

详细教程和接口定义随包提供，也可在线阅读：

- [配置、Windows操作、断点恢复与采集原理](../../../../BOSSARD_COLLECTOR_GUIDE.md)
- [命令行、Python函数与JSON字段定义](../../../../BOSSARD_COLLECTOR_API.md)

`checksums.json` 提供文件大小和SHA-256。工具包仅包含公开采集数据、缓存、代码与说明，不包含业务数据库、账号或环境密钥。所有审核选择默认“待审核”；不要覆盖已经人工审核的副本。Python流程和解压包离线导出在Linux验证，Windows启动文件需在实际Windows电脑上运行确认。
