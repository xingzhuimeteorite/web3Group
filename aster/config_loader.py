import json
import os
from typing import Dict, Any


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_file: str = "config.json"):
        """
        初始化配置加载器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = {}
        self.load_config()
    
    def load_config(self) -> None:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            print(f"配置文件 {self.config_file} 不存在")
            print("请复制 config.json.template 为 config.json 并填入您的API密钥")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except json.JSONDecodeError as e:
            print(f"配置文件格式错误: {e}")
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_api_credentials(self) -> Dict[str, str]:
        """
        获取API凭证
        
        Returns:
            包含api_key和secret_key的字典
        """
        return {
            'api_key': self.get('api_key', ''),
            'secret_key': self.get('secret_key', ''),
            'base_url': self.get('base_url', 'https://fapi.asterdex.com')
        }
    
    def is_configured(self) -> bool:
        """
        检查是否已配置API密钥
        
        Returns:
            是否已配置
        """
        api_key = self.get('api_key', '')
        secret_key = self.get('secret_key', '')
        
        return (api_key and api_key != 'your_api_key_here' and 
                secret_key and secret_key != 'your_secret_key_here')