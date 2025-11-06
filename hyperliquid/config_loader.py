#!/usr/bin/env python3
"""
配置文件加载器
用于加载和管理hyperliquid监控系统的配置
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class FeishuConfig:
    """飞书配置"""
    webhook_url: str
    enable_notifications: bool = True
    alert_threshold: float = 50000.0
    batch_summary: bool = True
    timeout: int = 10
    retry_times: int = 3


@dataclass
class MonitoringConfig:
    """监控配置"""
    check_interval_minutes: int = 10
    max_concurrent_checks: int = 5
    position_change_threshold: float = 0.05
    pnl_alert_threshold: float = 10000.0
    save_history: bool = True


@dataclass
class WhaleDetectionConfig:
    """巨鲸检测配置"""
    min_position_value: float = 100000.0
    mega_whale_threshold: float = 10000000.0
    super_whale_threshold: float = 50000000.0


@dataclass
class HyperliquidConfig:
    """完整的hyperliquid配置"""
    feishu: FeishuConfig
    monitoring: MonitoringConfig
    whale_detection: WhaleDetectionConfig


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._config_data: Optional[Dict[str, Any]] = None
        
    def load_config(self) -> HyperliquidConfig:
        """
        加载配置文件
        
        Returns:
            HyperliquidConfig: 配置对象
            
        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误
        """
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"配置文件不存在: {self.config_path}\n"
                f"请复制 config.json.template 到 config.json 并填入正确的配置信息"
            )
            
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config_data = json.load(f)
                
            return self._parse_config()
            
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件JSON格式错误: {e}")
        except Exception as e:
            raise ValueError(f"加载配置文件失败: {e}")
            
    def _parse_config(self) -> HyperliquidConfig:
        """解析配置数据"""
        if not self._config_data:
            raise ValueError("配置数据为空")
            
        # 解析飞书配置
        feishu_data = self._config_data.get('feishu', {})
        feishu_config = FeishuConfig(
            webhook_url=feishu_data.get('webhook_url', ''),
            enable_notifications=feishu_data.get('enable_notifications', True),
            alert_threshold=feishu_data.get('alert_threshold', 50000.0),
            batch_summary=feishu_data.get('batch_summary', True),
            timeout=feishu_data.get('timeout', 10),
            retry_times=feishu_data.get('retry_times', 3)
        )
        
        # 验证必需的配置
        if not feishu_config.webhook_url or feishu_config.webhook_url == "your_feishu_webhook_url_here":
            print("⚠️  警告: 飞书webhook未配置，推送功能将被禁用")
            feishu_config.enable_notifications = False
            
        # 解析监控配置
        monitoring_data = self._config_data.get('monitoring', {})
        monitoring_config = MonitoringConfig(
            check_interval_minutes=monitoring_data.get('check_interval_minutes', 10),
            max_concurrent_checks=monitoring_data.get('max_concurrent_checks', 5),
            position_change_threshold=monitoring_data.get('position_change_threshold', 0.05),
            pnl_alert_threshold=monitoring_data.get('pnl_alert_threshold', 10000.0),
            save_history=monitoring_data.get('save_history', True)
        )
        
        # 解析巨鲸检测配置
        whale_data = self._config_data.get('whale_detection', {})
        whale_config = WhaleDetectionConfig(
            min_position_value=whale_data.get('min_position_value', 100000.0),
            mega_whale_threshold=whale_data.get('mega_whale_threshold', 10000000.0),
            super_whale_threshold=whale_data.get('super_whale_threshold', 50000000.0)
        )
        
        return HyperliquidConfig(
            feishu=feishu_config,
            monitoring=monitoring_config,
            whale_detection=whale_config
        )
        
    def get_feishu_config(self) -> FeishuConfig:
        """获取飞书配置"""
        config = self.load_config()
        return config.feishu
        
    def get_monitoring_config(self) -> MonitoringConfig:
        """获取监控配置"""
        config = self.load_config()
        return config.monitoring
        
    def get_whale_detection_config(self) -> WhaleDetectionConfig:
        """获取巨鲸检测配置"""
        config = self.load_config()
        return config.whale_detection


def load_config(config_path: str = "config.json") -> HyperliquidConfig:
    """
    便捷函数：加载配置
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        HyperliquidConfig: 配置对象
    """
    loader = ConfigLoader(config_path)
    return loader.load_config()


if __name__ == "__main__":
    # 测试配置加载
    try:
        config = load_config()
        print("✅ 配置加载成功")
        print(f"飞书推送: {'启用' if config.feishu.enable_notifications else '禁用'}")
        print(f"监控间隔: {config.monitoring.check_interval_minutes} 分钟")
        print(f"并发检查数: {config.monitoring.max_concurrent_checks}")
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")