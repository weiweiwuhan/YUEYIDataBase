AOI DATAS · 岳一科技数据资产中枢 V1.9.1

完整使用说明见 README.md；当前版本和更新时间见 version.json。

1.9.1 材质与工艺维护
在“数据录入”选择材质字典或工艺字典，点击“详情与关联”。
名称写错可直接编辑；产品选错可更正产品材质或工艺绑定。
管理员可逐条解除材质/工艺绑定，处理完引用后在同一窗口删除字典条目。
解除关系保留产品、图片和工程资料；修改已验证经验的范围前需核实测试依据。

1.9.0 紧固件公开目录
- 新增独立外部目录，保存来源分类树、BN系列、头型、驱动槽型、螺纹、
  材质、材料类型、制造材料、性能等级、表面处理、颜色、标准及来源URL。
- BN系列与公司具体产品规格分开，公开缺失字段留空，不自动猜测或合并。
- Excel默认待审核。管理员把审核通过的行改“是”，进入“紧固件目录”，
  先预览校验再确认更新；只补空值、保留冲突，重复导入不重复建档。
- 分类候选仅供核实，确认后填写分类编号；三种材料字段独立保存。
- 当前共34张业务表。启动创建目录表，不自动导入待审核工作簿。
- 可选采集脚本与本地命令见 CATALOG_IMPORT.md；采集依赖单独安装。
  实际采集范围以工作簿采集报告为准，样本不代表完整实时目录。

首页建设初衷（1.8.1）
把分散的检测资料沉淀为公司可复用的知识资产，让资料查得快、经验传得下，
为后续 AI 应用积累准确、一致、有代表性且可追溯的数据与知识。
首页展示资料留存、标准对齐、测试追溯和经验复用的路径，并保留统计与日常工作台。

1.8.0 功能更新
1. Word 第一页、PPT 第一张幻灯片、PDF 首页自动生成封面。
   服务启动后后台为已导入的本地文档补生成；浏览时也会按需生成。
   保留自定义封面及原文件；NAS、压缩包成员和缺失原文件的记录跳过。
2. AI 智能问答实时流式显示，提供停止回答、进度、参考来源、私人历史和反馈。
   传输中断时明确提示，半截文字不会作为完整模型回答保存。
3. 知识关联补齐材质、工艺和分类层级，统一全角半角、大小写与空白。
   同名对象需要补充规格、版本或完整对象编号，不自动合并。
4. 已验证关系检查测试是否覆盖适用对象；问答过滤明确冲突的产品和测试条件。
   逐条关联可登记依据文档、页码、表格或视频时间点。未知条件仍保留为未知。
5. schema.py 统一字段长度、范围和单位，导出 MySQL DDL 与 JSON Schema。
   GitHub Actions 自动执行回归、Office 首页和生成结果一致性检查。

本地启动
- Python 3.10 或以上；建议独立虚拟环境。
- 安装依赖：python -m pip install -r requirements.txt
- Windows 可使用 start.bat；公司内网共享使用 start-lan.bat。
- 直接启动：python app.py --no-browser
- 默认地址：http://127.0.0.1:8765；默认 SQLite，也保留 MySQL 支持。
- 首次运行用 python manage_users.py 创建管理员，没有默认账号或公共密码。
- AOI_DATA 指定实际业务数据目录，初始化、启动及维护命令须保持一致。

封面依赖
- Word/PPT：在运行服务的电脑安装 LibreOffice，常见安装路径自动识别。
- 非标准安装路径：设置 AOI_SOFFICE 指向 soffice.exe 或 soffice。
- PDF：PyMuPDF，已加入 requirements.txt 和启动依赖检查。
- 视频首帧：ffmpeg。
- Dockerfile 已配置 LibreOffice、PyMuPDF、ffmpeg 与中文字体依赖。
- 手动补生成历史文档封面：python backfill_previews.py
- 只读检查历史知识：python verify_knowledge.py

AI 智能问答
- 设置 AOI_RAG_API_KEY，默认使用 DeepSeek；具体配置见 RAG_ASSISTANT.md。
- 未配置模型时仍可检索本地知识原文，不会伪装成模型回答。
- 上传附件和生成封面不等于把附件正文导入知识库；关键步骤与条件请写入经验正文。
- 使用 Nginx 等反向代理时，为 /api/assistant/chat-stream 关闭响应缓冲，
  并允许至少 120 秒读取等待；应用会发送 X-Accel-Buffering: no。

升级现有工程
1. 停止旧服务，完整备份实际 AOI_DATA；MySQL 另外备份数据库。
2. 更新全部程序文件，保留原数据目录，不用仓库里的示例数据覆盖业务数据。
3. 安装新版 requirements.txt，按需安装 LibreOffice。
4. 重启服务并按 Ctrl+F5 刷新浏览器。启动自动增量升级，保留原 ID、关联与附件。
5. 检查左下角版本为 1.9.1，并验证登录、已有文件、问答和紧固件目录。

开发验证
python -m pip install -r requirements-dev.txt
python -m unittest discover -p 'test_*.py' -q
node test_assistant_ui.js
node test_image_search.js
node test_offline_ui.js
node test_catalog_ui.js
python export_contract.py --check

目录解析和导入测试使用离线样例及隔离数据库，不代表已经完成实站全量采集。
真实 MySQL 升级、DeepSeek 服务连接和 Docker 部署需在目标环境另行验证。
