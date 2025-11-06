"""
配置项目范围的日志记录器。
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

def setup_logger(project_root: str, name: str = 'funding_arbitrage') -> logging.Logger:
    """
    设置一个日志记录器，该记录器会输出到控制台和按天轮换的文件中。

    Args:
        project_root (str): 项目的根目录路径。
        name (str): 日志记录器的名称。

    Returns:
        logging.Logger: 配置好的日志记录器实例。
    """
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        # 如果已经配置过，直接返回，避免重复添加处理器
        return logger

    logger.setLevel(logging.INFO)

    # 创建 logs 目录（如果不存在）
    log_dir = os.path.join(project_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # 定义日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # --- 控制台处理器 ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # --- 文件处理器（按天轮换） ---
    log_file_path = os.path.join(log_dir, 'observer.log')
    # when='midnight' 表示每天午夜轮换，backupCount=30 表示保留30天的日志
    file_handler = TimedRotatingFileHandler(
        log_file_path, when='midnight', interval=1, backupCount=30, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger