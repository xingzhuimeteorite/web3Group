#!/usr/bin/env python3
import json
from pathlib import Path


def load_config():
    """加载 funding_arbitrage/config 下的配置（优先 config.json，回退模板）。"""
    root_dir = Path(__file__).resolve().parent.parent
    cfg_path = root_dir / "config" / "config.json"
    if not cfg_path.exists():
        cfg_path = root_dir / "config" / "config.json.template"
        print(f"[WARN] 未找到 config.json，使用模板：{cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg, cfg_path