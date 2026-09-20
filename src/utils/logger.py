"""结构化日志配置：统一日志格式与级别

开发期：控制台输出 INFO 级别及以上
生产期：文件输出 DEBUG 级别，便于排查问题
"""
import logging
import sys
from pathlib import Path

# 日志格式：时间 - 模块 - 级别 - 消息
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> None:
    """配置全局日志

    Args:
        level: 日志级别，默认 INFO
        log_file: 日志文件路径，None 则只输出到控制台
    """
    # 根 logger
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler（避免重复添加）
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件 handler（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # 文件记录更详细
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # 降低第三方库日志级别
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger"""
    return logging.getLogger(name)
