"""
日志配置
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config.settings import settings


def setup_logging(
    name: str = "agent_teams",
    log_level: str = None,
    log_file: str = None
) -> logging.Logger:
    """
    配置日志

    Args:
        name: 日志器名称
        log_level: 日志级别
        log_file: 日志文件路径

    Returns:
        配置好的日志器
    """
    logger = logging.getLogger(name)

    # 设置日志级别
    level = (log_level or settings.log_level).upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    # 清除现有处理器
    logger.handlers = []

    # 格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器
    if log_file or settings.log_file:
        log_path = Path(log_file or settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# 全局日志器
logger = setup_logging()
