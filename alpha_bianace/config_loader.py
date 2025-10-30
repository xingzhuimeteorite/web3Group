#!/usr/bin/env python3
"""
Alpha Binance 监控配置加载器
解析 conf.conf 文件中的配置信息
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class MonitorConfig:
    """监控配置数据类"""
    monitor_url: str
    feishu_webhook_url: str = ""
    check_interval: int = 60*60  # 检查间隔（秒）
    timeout: int = 30  # 请求超时时间（秒）
    max_retries: int = 3  # 最大重试次数
    enable_logging: bool = True  # 是否启用日志


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_file: str = "conf.conf"):
        """
        初始化配置加载器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config_path = self._get_config_path()
        
    def _get_config_path(self) -> str:
        """获取配置文件的完整路径"""
        # 如果是相对路径，则相对于当前脚本所在目录
        if not os.path.isabs(self.config_file):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            return os.path.join(script_dir, self.config_file)
        return self.config_file
    
    def load_config(self) -> MonitorConfig:
        """
        加载配置文件
        
        Returns:
            MonitorConfig: 配置对象
            
        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误或缺少必需配置
        """
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        config_data = {}
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # 跳过空行和注释行
                    if not line or line.startswith('#'):
                        continue
                    
                    # 解析键值对
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        config_data[key] = value
                    else:
                        print(f"⚠️  警告: 第{line_num}行格式不正确，已跳过: {line}")
        
        except Exception as e:
            raise ValueError(f"读取配置文件失败: {e}")
        
        # 验证必需的配置项
        if 'monitor_url' not in config_data:
            raise ValueError("配置文件中缺少必需的 'monitor_url' 配置")
        
        # 创建配置对象
        config = MonitorConfig(
            monitor_url=config_data['monitor_url'],
            feishu_webhook_url=config_data.get('feishu_webhook_url', ''),
            check_interval=int(config_data.get('check_interval', 60)),
            timeout=int(config_data.get('timeout', 30)),
            max_retries=int(config_data.get('max_retries', 3)),
            enable_logging=config_data.get('enable_logging', 'true').lower() == 'true'
        )
        
        return config
    
    def validate_config(self, config: MonitorConfig) -> bool:
        """
        验证配置的有效性
        
        Args:
            config: 配置对象
            
        Returns:
            bool: 配置是否有效
        """
        # 验证监控URL
        if not config.monitor_url or not config.monitor_url.startswith(('http://', 'https://')):
            print("❌ 监控URL无效")
            return False
        
        # 验证数值配置
        if config.check_interval <= 0:
            print("❌ 检查间隔必须大于0")
            return False
        
        if config.timeout <= 0:
            print("❌ 超时时间必须大于0")
            return False
        
        if config.max_retries < 0:
            print("❌ 最大重试次数不能为负数")
            return False
        
        return True
    
    def print_config(self, config: MonitorConfig) -> None:
        """
        打印配置信息
        
        Args:
            config: 配置对象
        """
        print("\n" + "="*50)
        print("📋 当前配置信息")
        print("="*50)
        print(f"🌐 监控URL: {config.monitor_url}")
        print(f"🔔 飞书Webhook: {'已配置' if config.feishu_webhook_url else '未配置'}")
        print(f"⏱️  检查间隔: {config.check_interval}秒")
        print(f"⏰ 请求超时: {config.timeout}秒")
        print(f"🔄 最大重试: {config.max_retries}次")
        print(f"📝 启用日志: {'是' if config.enable_logging else '否'}")
        print("="*50)


def load_config(config_file: str = "conf.conf") -> MonitorConfig:
    """
    便捷函数：加载配置
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        MonitorConfig: 配置对象
    """
    loader = ConfigLoader(config_file)
    config = loader.load_config()
    
    if not loader.validate_config(config):
        raise ValueError("配置验证失败")
    
    return config


if __name__ == "__main__":
    """测试配置加载器"""
    print("🧪 测试配置加载器...")
    
    try:
        config = load_config()
        loader = ConfigLoader()
        loader.print_config(config)
        print("✅ 配置加载成功")
        
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")