# Bossard 审核文件与续采工具（2026-11-11）

本目录用于文件交付，不会自动导入业务库。采集到 39 个分类节点、391 个 BN 系列，另有 317 个候选待续采。采集检测到 HTTP 403 后停止，尚未完成全量；产品分类归属仅为候选，需人工核实。

## 下载

- [审核 Excel](Bossard_review_391_BN.xlsx)
- [审核数据、缓存和续采工具包](Bossard_review_and_resume_tools.zip)
- [317 个待续采 BN 清单](pending_317_BN.csv)

点击文件名进入 GitHub 文件页，再点右上角的 **Download raw file（下载原始文件）** 图标。若直接下载链接要求登录，请先登录有仓库权限的 GitHub 账号。

也可以在本地仓库执行 `git pull`，文件即位于 `review_exports/bossard/2026-11-11/`；或者在仓库首页点击 **Code → Download ZIP** 下载整个仓库后解压。

`checksums.json` 提供文件大小和 SHA-256，供核对下载完整性。工具包内包含缓存、公开采集数据和续采说明，不包含业务数据库、账号清单或环境密钥。请在审核副本上操作，不要覆盖原始交付文件。
