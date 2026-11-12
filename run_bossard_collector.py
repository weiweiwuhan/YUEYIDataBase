"""本地采集的配置入口：读 JSON 参数，以当前 Python 启动独立采集脚本。

三种模式：resume=继续采集属性及主图；images-only=只补已有产品主图；
export=完全离线，用 cache/export-data.json 重新导出 Excel。
命令：python run_bossard_collector.py --mode images-only
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = {
    "categories": "categories.json",
    "cache": "cache",
    "output_dir": "output",
    "delay": 3.0,
    "max_products": 0,
    "max_category_pages": 1000,
    "max_sitemap_pages": 200,
    "browser_executable": "",
    "download_images": True,
    "embed_images": True,
}


def load_config(path: Path) -> dict:
    """读取 UTF-8 JSON 配置，补默认值并拒绝未知字段和错误类型。

    所有相对路径都相对于配置文件所在目录。返回纯字典，不创建目录或联网。
    配置不包含密码、API Key 或网站登录信息。
    """
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("配置根节点必须是 JSON 对象")
    unknown = set(config) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError("未知配置项：" + ", ".join(sorted(unknown)))
    config = {**DEFAULT_CONFIG, **config}
    for key in ("categories", "cache", "output_dir", "browser_executable"):
        if not isinstance(config[key], str) or (
            key != "browser_executable" and not config[key].strip()
        ):
            raise ValueError(key + " 必须是有效路径字符串")
    for key in ("download_images", "embed_images"):
        if type(config[key]) is not bool:
            raise ValueError(key + " 必须使用 JSON 的 true 或 false")
    for key, minimum in (
        ("max_products", 0),
        ("max_category_pages", 1),
        ("max_sitemap_pages", 1),
    ):
        if type(config[key]) is not int or config[key] < minimum:
            raise ValueError(key + " 必须是大于等于 " + str(minimum) + " 的整数")
    delay = config["delay"]
    if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 1:
        raise ValueError("delay 必须是大于等于1的有限秒数")
    return config


def build_command(config: dict, base: Path, mode: str, output: Path) -> list[str]:
    """把配置转换为采集 CLI 参数列表，不执行命令。

    base 为配置目录，output 为本次新 Excel 路径；mode 支持 resume、images-only、
    export。列表交给 subprocess.run，不使用 shell=True，目录含空格也能传递。
    """
    if mode not in ("resume", "images-only", "export"):
        raise ValueError("未知模式：" + mode)

    def resolve(value):
        return str((base / Path(value).expanduser()).resolve())

    cache = Path(resolve(config["cache"]))
    command = [
        sys.executable,
        str(Path(__file__).with_name("bossard_catalog.py")),
        "--categories",
        resolve(config["categories"]),
        "--output",
        str(output),
    ]
    if mode == "export":
        command += [
            "--products",
            str(cache / "export-data.json"),
            "--image-root",
            str(cache),
        ]
    else:
        command += [
            "--crawl",
            "--cache",
            str(cache),
            "--delay",
            str(config["delay"]),
            "--max-products",
            str(config["max_products"]),
            "--max-category-pages",
            str(config["max_category_pages"]),
            "--max-sitemap-pages",
            str(config["max_sitemap_pages"]),
        ]
        if mode == "images-only":
            if not config["download_images"]:
                raise ValueError("只补图模式要求 download_images=true")
            command.append("--images-only")
        if config["browser_executable"]:
            command += ["--browser-executable", resolve(config["browser_executable"])]
        if not config["download_images"]:
            command.append("--skip-images")
    if not config["embed_images"]:
        command.append("--no-embed-images")
    return command


def main() -> int:
    """运行入口。每次使用带时间戳的新文件名，避免覆盖已人工审核的 Excel。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("collector_config.json")
    )
    parser.add_argument(
        "--mode", choices=("resume", "images-only", "export"), default="resume"
    )
    args = parser.parse_args()
    try:
        config_path = args.config.resolve()
        config = load_config(config_path)
        base = config_path.parent
        output_dir = (base / config["output_dir"]).resolve()
        output = output_dir / (
            "Bossard_"
            + args.mode
            + "_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + ".xlsx"
        )
        command = build_command(config, base, args.mode, output)
        # 导出只读已有JSON。前置检查可以让双击运行时直接看到缺了哪个文件。
        categories = (base / config["categories"]).resolve()
        if not categories.is_file():
            raise ValueError("找不到分类种子：" + str(categories))
        cache = (base / config["cache"]).resolve()
        if args.mode == "export" and not (cache / "export-data.json").is_file():
            raise ValueError(
                "找不到 cache/export-data.json；请先采集或使用包内原始缓存"
            )
        if (
            args.mode == "images-only"
            and not (cache / "category-checkpoint.json").is_file()
        ):
            raise ValueError("只补图需要已有缓存，请先采集或沿用工具包的 cache 目录")
        output_dir.mkdir(parents=True, exist_ok=True)
        print("本次输出：" + str(output), flush=True)
        print("执行参数：" + shlex.join(command), flush=True)
        return subprocess.run(command, cwd=base, check=False).returncode
    except (OSError, ValueError) as error:
        print("配置或运行失败：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
