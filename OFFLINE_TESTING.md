# 本地大模型离线测试

网页服务器必须运行在能够访问模型工程、训练检查点和 Python 环境的电脑上。浏览器所在电脑上传图片后，推理发生在服务器的本地 Python 环境中，不向外部 AI 服务发送图片。云端工作区不能直接访问你的 Windows F: 盘。

## 模型配置

在运行网页服务的 Windows 电脑打开终端，进入本项目目录。使用与网页服务相同的 `AOI_DATA` 环境设置，运行：

```text
python configure_offline.py
```

如果启动网页使用 `py -3`，也可以运行 `py -3 configure_offline.py`。这条命令只写配置并检查路径，不会加载或执行模型。配置默认保存为 `AOI_DATA/offline_models.json`；未设置 `AOI_DATA` 时为本项目 `data/offline_models.json`。如果网页使用了 `AOI_OFFLINE_MODELS` 自定义位置，请用 `--output` 指定同一路径。已有配置默认不覆盖，确认需要重建时加 `--force`。命令支持 `--project-dir`、`--python`、`--checkpoint-dir`、`--backbone-weights`，可用 `--help` 查看。

也可以复制 `offline_models.example.json` 手动配置。示例使用你提供的工程路径 `F:/Fighting!!!!!!!!!!/MyDinoFiuntune`、检查点目录 `.../checkpoints` 和 Python 安装目录 `C:/ProgramData/anaconda3`，Python 可执行文件为 `C:/ProgramData/anaconda3/python.exe`。如果模型在独立 Conda 环境中，请改为对应 `envs/<环境>/python.exe`。

基础权重 `F:/Fighting!!!!!!!!!!/UniADet-main/dinov3/model.safetensors` 仅来自你上传的参考脚本，尚未在实际电脑核验，请确认存在并修改为真实路径。`project_dir` 必须包含 `config.py`、`models/dinov3.py`、`models/feature_extractor.py` 和 `models/weidino.py`。训练检查点须包含 `model_state_dict`，或本身为纯 state_dict。支持使用配置中的 `checkpoint_dir` 扫描 `.pt/.pth`，也可按主服务要求填写显式 `models`。

这些是服务器管理员维护的可信配置。不要通过浏览器上传 Python 程序、修改执行命令或让普通访问者填写服务器路径。

## 模型环境依赖

用配置中的 Python 安装匹配的 PyTorch、torchvision、numpy、Pillow、safetensors，以及模型工程自己的依赖；可参考 `requirements-offline.txt`。CUDA 版本需与显卡驱动和 PyTorch 构建匹配，按 PyTorch 官方安装说明选择 torch/torchvision 配对版本。无需将这些大依赖装到只负责网页的虚拟环境。

`device=auto` 按 CUDA → MPS → CPU 选择；也可指定 `cpu`、`cuda` 或 `mps`，指定不可用设备会明确失败。适配器没有参考脚本中的无条件 `.cuda()`，在 CPU 环境也使用相同模型流程。模型按 `torch.inference_mode()` 执行，检查点使用 `weights_only=True`，不会在安全加载失败后退回不安全的 pickle 加载。如果现有检查点包含非张量对象，请在你信任的原训练工程内将 `model_state_dict` 单独另存后使用。

参考脚本默认 `use_memory=False`；本版保持这一设置。当前没有接入 MemoryBank 融合，因为它的本地类实现和安全加载接口未提供；配置非空 `memory_bank` 会明确报错，不会静默忽略。

## 预测语义

适配器保留参考脚本的 512×512（可配置）Resize、ImageNet 均值标准差、`FeatureExtractor` 层 `[4,12,16,20]` 和 `ImprovedAnomalyDetector` 初始化参数。必须与该检查点的训练配置一致，不能随意改变尺寸、特征层或模型结构。

模型需返回 `seg_map` 与可选 `image_score`；`seg_map` 支持 `[H,W]`、`[1,H,W]`、`[1,1,H,W]`。缺少 `image_score` 时才使用分割分数最大值。输出分数保持模型原始尺度，可能不在 0–1 区间；阈值需使用实际正常/缺陷样本标定。不会用单张图的 min/max 拉伸来决定 OK/NG，避免“每张正常图片也被拉伸成高响应”的错误。

原参考脚本把 `label` 固定为 0，因而不会画缺陷框；网页后处理应根据设定阈值生成分割区域并在原始分辨率图片上叠加，不沿用固定标签。热力显示与最终判定应分开理解，模型结果是辅助测试结果，不代表已经过量产验证的质量结论。

## 适配器命令行与进程协议

`offline_runner.py` 接收**一条已合并默认值、选定检查点后的模型配置对象**，不是整个模型清单。

```text
<模型环境的python> offline_runner.py --model-json <单模型配置.json> --input <图片> --output <分数.npy>
```

正常输出一行 JSON，包含 `ok`、`image_score`、分割图 `height` 和 `width`；分割分数文件是 float32 的 H×W `.npy`，不包含 pickle 对象。失败退出码为 1，并输出错误 JSON。

队列使用持久化模式避免同一个模型每张图重新加载：

```text
<模型环境的python> offline_runner.py --model-json <单模型配置.json> --serve
```

加载成功输出 `{"ready":true}`。每个 stdin 行为 `{"input":"本地图片路径","output":"本地分数.npy"}`；每张图处理后输出一行结果。单图失败输出 `{"ok":false,"error":"原因"}` 并继续等待下一张。标准输出仅用于协议，模型工程打印重定向到标准错误；主服务应将标准错误写日志文件，不能使用无人读取的 stderr PIPE。

未提供实际模型工程和权重时，只能验证队列、接口和后处理，不能声称真实模型预测通过。当前云环境不具备你的 Windows 本地文件，真实模型的加载与效果需在你的电脑完成验证。

## 网页队列与参数

登录后进入左侧“大模型离线测试”，选择模型、设置参数，再选择或拖拽图片提交。单张也是独立队列任务；批量任务每完成一张立即可查看该张结果，不必等全部完成。队列按批次先进先出，单个网页服务进程只启动一个推理工作进程，同一批次模型只加载一次。运行多个网页服务进程会各自创建队列，当前版本应只运行一个服务进程来管理同一个 GPU/数据目录。

- 分割阈值：对原始响应图进行高斯平滑、恢复到原图尺寸后，以“分数大于阈值”生成候选区域。不做逐图 min/max 归一化。
- 最小缺陷面积：在原图像素尺度过滤小连通区域。
- 图像判定阈值：可留空；填写时，图像分数低于门限会抑制全部分割区域。
- 透明度只影响红色叠加显示；平滑强度的单位是模型响应图网格像素。
- “调整分割参数”处理保存的 `.npy` 原始分数图，不重新执行模型。原图始终保留。高噪声图片仅保存前 2000 个框的坐标，完整二值掩码和区域总数仍保留。

每批最多 200 张/512 MB，单图最多 32 MB/2000 万像素。单图推理超时为 180 秒；模型加载默认 180 秒，可在可信模型配置里设置 `load_timeout`。取消任务会跳过尚未执行的图片，当前一张可能在完成后才停止。服务重启会保留已完成图和结果；执行中任务标记中断，不会假装成功，重新提交即可再次预测。排队中任务在进程启动队列后继续调度。

任务和图片以登录账号隔离，只有本人或管理员可以读取结果。状态、原图、分割分数、掩码、叠图及模型加载日志位于 `AOI_DATA/offline_tests`，应随整个数据目录备份，并定期由管理员清理不再需要的测试任务。界面不会把模型结果自动写入正式缺陷表。

测试命令：`python -m unittest -v test_offline test_offline_http`、`node test_offline_ui.js`。测试专用预测进程只存在于临时测试目录，验证的是队列、接口和后处理，不代表真实模型精度或速度已验证。

## 检查点安全加载失败的处理

该提示并不代表上传图片失败。训练检查点可能包含优化器、NumPy 对象或配置对象，而网页仅允许纯权重安全加载。现在错误提示会保留原始加载原因，帮助区分文件损坏、版本不兼容和附加对象。

在网页项目目录，用原模型 Python 执行（将文件名换成实际选中的检查点）：

```bat
"C:\ProgramData\anaconda3\python.exe" convert_checkpoint.py "F:\Fighting!!!!!!!!!!\MyDinoFiuntune\checkpoints\uniadet_best_yashang.pt"
```

默认仍用 weights_only=True。如果仍失败，**仅当此文件是你自己训练或完全可信的检查点**，在本机命令末尾增加 `--trust-source`。该开关会在本机读取可信训练对象，不能用于下载来的未知模型；网页服务从不启用它。转换工具只保留张量权重，用 weights_only=True 重新加载并逐张量验证一致后，生成同目录 `uniadet_best_yashang.safe.pt`，不覆盖原检查点。

刷新离线测试页面，在模型列表改选带 `.safe` 的新模型，重新提交图片；此前失败任务不会自动重跑。检查点目录会自动扫描新文件，无需改模型代码。若原始原因显示文件损坏或缺少原工程依赖，应先修复对应问题，转换工具不保证能修复损坏文件。
