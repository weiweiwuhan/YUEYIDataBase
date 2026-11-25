# 本地大模型离线测试

网页服务器运行在能够访问 MyDinoFiuntune 工程、检查点和模型 Python 环境的电脑上。浏览器上传图片后，由服务器本地模型预测，不发送到外部 AI 服务。云端工作区不能直接访问 Windows F: 盘。

## 1.12.0 默认模型与目录

本版本按最新 MyDinoFiuntune 的统一推理接口加载，不再固定使用旧参考脚本的 `ImprovedAnomalyDetector`。

| 配置 | 默认值 |
| --- | --- |
| 模型 Python | `C:/ProgramData/anaconda3/python.exe` |
| 完整模型工程 | `F:/Fighting!!!!!!!!!!/MyDinoFiuntune` |
| 检查点目录 | `F:/Fighting!!!!!!!!!!/MyDinoFiuntune/checkpoints/anomaly` |
| 自动搜索 | `.pt`，包含子目录，扩展名大小写不敏感 |
| 加载后端 | `unified`，调用工程的 `models.task_model.load_checkpoint` |
| 预处理 | 工程的 `data.dataset.get_image_transform` |
| 阈值 | 0～1，分割默认 0.5，平滑默认 0 |

先更新**完整模型工程**，至少需要 `models/task_model.py`、`data/dataset.py` 及其引用的其他模块和依赖。只复制训练权重到旧工程不足以支持新格式。

检查点需要保留 `format_version=2`、`model_config`、`model_state`、`image_size`，以及工程保存的 `preprocessing`、`classes` 等信息。这是含完整网络权重的检查点，推理不再额外加载旧 `model.safetensors`。**不要用旧转换工具将新版文件转换为裸 state_dict**。

把检查点放入上述目录后，在左侧“大模型离线测试”点击“刷新模型列表”。子目录中的同名文件会显示相对路径，例如 `trial-a/best`、`trial-b/best`。模型文件和 Python 代码只由本机管理员维护，网页不接受模型代码、执行命令或服务器路径上传。

## 模型配置与已有配置升级

默认路径无需创建配置文件即可发现模型。自定义路径时，在网页项目目录、使用与服务相同的 `AOI_DATA`，运行：

```bat
python configure_offline.py --project-dir "F:\Fighting!!!!!!!!!!\MyDinoFiuntune" --python "C:\ProgramData\anaconda3\python.exe"
```

配置写入 `AOI_DATA/offline_models.json`；未设置 `AOI_DATA` 时为本项目 `data/offline_models.json`。网页若设置了 `AOI_OFFLINE_MODELS`，用 `--output` 指向同一文件。也可参考 [offline_models.example.json](offline_models.example.json)。

| 参数/字段 | 用法 |
| --- | --- |
| `--project-dir` / `defaults.project_dir` | 完整模型工程目录 |
| `--python` / `defaults.python` | 实际模型环境的 Python；独立 Conda 环境指向 `envs/<环境>/python.exe` |
| `--checkpoint-dir` / `checkpoint_dir` | 默认工程下 `checkpoints/anomaly`，可改为其他可信目录 |
| `--no-recursive` / `recursive=false` | 只搜索当前层；默认递归 |
| `defaults.device` | `auto` 按 CUDA → MPS → CPU；也可明确指定，设备不可用会报错 |
| `models` | 可显式登记检查点、ID、名称和后端；自动搜索跳过已登记的同一文件 |
| `--backend` / `defaults.backend` | 新模型用 `unified`；旧工程可选 `dinov3`，兼容 TorchScript 可选 `torchscript` |
| `--output` | 配置文件位置 |
| `--force` | 明确覆盖已有配置；默认拒绝覆盖，使用前先备份 |

命令只检查路径、写配置，不执行模型。网页进程也不导入 PyTorch；真正加载发生在独立模型进程。新增文件需刷新列表，修改配置后建议重新提交任务。

升级规则：旧默认配置（无配置版本号，`backend=dinov3`、目录为工程的 `checkpoints`）会在读取时自动转为搜索 `checkpoints/anomaly` 并使用新后端，**不会重写原配置文件**。旧配置如果已经指向名为 `anomaly` 的目录，也按新后端搜索。显式 `models` 条目、其他自定义目录及明确写有配置版本 `format_version=2` 的后端不自动改动。自定义旧配置需要自行改为 `backend=unified` 和正确目录。新目录不存在时明确提示，不回退到旧根目录误选模型。

## 模型环境依赖与安全加载

用配置中的 Python 安装匹配的 PyTorch、torchvision、NumPy、Pillow、safetensors 及完整模型工程依赖，可参考 [requirements-offline.txt](requirements-offline.txt)。按 PyTorch 官方说明选择兼容的 torch/torchvision、CUDA 和驱动组合，无需把模型依赖装进只负责网页的虚拟环境。

统一加载使用工程自己的 `load_checkpoint`；当前工程使用 `torch.load(..., weights_only=True)` 并按 `model_config` 重建结构、严格匹配权重。网页不在失败后改用 `weights_only=False`。如果加载失败，检查错误中的原始原因、工程版本、依赖和检查点完整性。加载错误不代表图片上传失败。

旧 `dinov3` 后端仍要求 `config.py`、`models/dinov3.py`、`models/feature_extractor.py`、`models/weidino.py` 及原 `.safetensors` 基础权重，可显式登记旧模型，或用 `configure_offline.py --backend dinov3 --checkpoint-dir ... --output <另存配置>` 生成配置后核对。仅旧工程的非纯权重检查点适用 [convert_checkpoint.py](convert_checkpoint.py)；该工具不能为新版统一模型补回被丢弃的配置和尺寸元数据。

MemoryBank 融合尚未接入，配置非空 `memory_bank` 会报错。

## 输入与分割语义

- `image_size=[高,宽]`：按检查点尺寸预测，支持非正方形；不固定改成 512×512。
- `image_size=null`：保持原尺寸，与最新 `infer.py` 一致，上传图片的高宽须分别为 32 的倍数；不符合时返回明确错误，不自动缩放。
- 灰度单通道与 RGB 三通道由模型决定，调用工程自己的转换函数。RGB 使用工程的 ImageNet 标准化，灰度保持其训练约定。
- 模型返回 `(image_score, probability_maps)`。二分类为 `[1,1,H,W]`，多分类为 `[1,C,H,W]`，包含背景类别 0。
- **分割图已由模型 sigmoid/softmax 转成 0～1**。适配器保留绝对分数，仅裁剪极小浮点越界；NaN/Inf 或明显越界会报错。不再次 sigmoid，也不逐图 min/max 拉伸，避免把正常图的微弱响应强行放大为 1。
- 二分类：概率图恢复至原图尺寸后，以 `概率 >= 分割阈值` 选取候选像素。
- 多分类：各类概率恢复至原图尺寸并重归一，再对包含背景的全部类别取 argmax；只保留获胜类别非背景且概率达到阈值的像素。不将全部前景类别相加后当作一种缺陷。
- 可选图像阈值也限制在 0～1，图像分数低于阈值时抑制分割区域。分数不是经过业务验证的检测准确率。

默认分割阈值 0.5、平滑 0。最小缺陷面积默认 8 个原图像素，会过滤小连通区域；要与工程默认逐像素掩码对照，设为 1，并关闭平滑、留空图像阈值。阈值最终应根据正常、缺陷和边界样本验证；不同模型相同分数不代表相同置信程度。

## 网页队列与重分割

登录后选择模型、设置参数，再拖拽或选择图片提交。一张图片对应一份结果，批量按批次先进先出，每完成一张立即可查看。同批模型只加载一次。单个网页进程只启动一个推理进程；同一 GPU 和数据目录应使用一个网页服务进程管理队列。

- 每批最多 200 张/512 MB；单张最多 32 MB/2000 万像素。
- 平滑在模型概率图尺度进行，单位为该图的像素；多分类只在空间方向平滑，不混合类别。
- 最小面积按原图像素过滤；透明度只改变红色叠加显示。
- “调整分割参数”读取保存的 `.npy`，不重新运行模型，保留原图。旧任务若保存超出 0～1 的原始响应，须重新预测后再调阈值；此前的原图和预览仍保留。
- 单图推理超时 180 秒，模型加载默认 180 秒，可通过可信配置的 `load_timeout` 修改加载期限。
- 取消跳过尚未执行的图片，当前图片可能完成后才停止。服务重启保留已完成结果；执行中任务标记中断，需重新提交，排队中任务继续调度。

原图、分数、掩码、叠图、状态及 `runner.log` 保存到 `AOI_DATA/offline_tests`，随整个数据目录备份。仅任务本人及管理员可以读取，界面不自动将结果写入正式缺陷记录。

## 适配器命令行与接口

`offline_runner.py` 接收**已合并默认值的单模型配置对象**，不是整个模型清单。例如：

```json
{
  "backend": "unified",
  "project_dir": "F:/Fighting!!!!!!!!!!/MyDinoFiuntune",
  "checkpoint": "F:/Fighting!!!!!!!!!!/MyDinoFiuntune/checkpoints/anomaly/best.pt",
  "device": "auto"
}
```

```text
<模型环境python> offline_runner.py --model-json <单模型.json> --input <图片> --output <分数.npy>
<模型环境python> offline_runner.py --model-json <单模型.json> --serve
```

单次运行输出一行 JSON：`ok`、`image_score`、`height`、`width`，失败退出码 1。分割文件为 float32 H×W 或 C×H×W 的 `.npy`，不含 pickle。持久模式加载成功输出 `{"ready":true,"model_info":{...}}`，包含后端、检查点版本、输入尺寸、通道、类别数和分数范围。每行 stdin 为 `{"input":"本地图片路径","output":"本地分数.npy"}`；每张返回一行结果，单图失败输出错误 JSON 后继续等待。标准输出保留给协议，模型打印重定向到写入日志的 stderr。

## 验证方法与范围

网页依赖环境运行队列、目录发现、权限、接口和后处理回归：

```text
python -m unittest -v test_offline test_offline_http test_offline_unified
node test_offline_ui.js
```

有完整模型源代码和模型依赖时，用**模型环境 Python** 设置 `AOI_TEST_MODEL_PROJECT` 指向完整工程，再运行 `python -m unittest -v test_offline_unified`。可选测试构建小型随机权重检查点，验证二分类、多分类、非正方形固定尺寸、原尺寸和尺寸错误提示，比较适配器与工程直接输出；缺少该环境时明确跳过这组测试。

本次在 CPU 环境用最新模型代码和随机权重验证了加载与输出契约；未读取用户实际训练权重，未在其 Windows/CUDA 电脑测量速度、显存或精度。更新后先选一个真实 `.pt`，上传一张已知正常图和一张已知缺陷图核对，再进行批量测试。
