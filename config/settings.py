"""
配置文件 - 统一从 src.settings 重新导出

所有配置定义集中在 src.settings，本模块仅为向后兼容而保留。
"""

import sys
import os

# 确保 src 目录在 Python 路径中
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from src.settings import Settings, settings  # noqa: E402, F401

__all__ = ["Settings", "settings"]
