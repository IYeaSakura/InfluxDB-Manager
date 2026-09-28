"""项目根目录入口：直接运行本文件即可启动 InfluxDB Manager。

用法：
    python main.py

等价于 ``python -m net.sakurain.influxdbstudio``，但不依赖项目是否已
执行过 ``pip install -e .``（自动把 ``src`` 加入模块搜索路径）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from net.sakurain.influxdbstudio.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
