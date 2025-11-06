#!/usr/bin/env python3
"""
巨鲸检测逻辑模块
基于仓位价值、PnL、风险指标等多维度识别和分类巨鲸
"""

import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from hyperliquid_api_client import UserPosition


class WhaleLevel(Enum):
    """巨鲸等级"""
    MEGA_WHALE = "mega_whale"      # 超级巨鲸 (>$50M)
    LARGE_WHALE = "large_whale"    # 大型巨鲸 ($10M-$50M)
    WHALE = "whale"                # 普通巨鲸 ($1M-$10M)
    DOLPHIN = "dolphin"            # 海豚 ($100K-$1M)
    FISH = "fish"                  # 小鱼 (<$100K)


class RiskLevel(Enum):
    """风险等级"""
    EXTREME = "extreme"    # 极高风险
    HIGH = "high"         # 高风险
    MEDIUM = "medium"     # 中等风险
    LOW = "low"          # 低风险
    SAFE = "safe"        # 安全


@dataclass
class WhaleProfile:
    """巨鲸档案"""
    address: str
    whale_level: WhaleLevel
    risk_level: RiskLevel
    total_position_value: float
    position_count: int
    total_pnl: float
    pnl_percentage: float
    leverage_score: float
    concentration_score: float
    activity_score: float
    risk_score: float
    confidence_score: float
    
    # 详细信息
    largest_position_value: float
    largest_position_coin: str
    avg_leverage: float
    max_leverage: float
    
    # 时间信息
    first_seen: str
    last_update: str
    
    # 标签
    tags: List[str]
    
    def __post_init__(self):
        if not self.tags:
            self.tags = []


class WhaleDetector:
    """巨鲸检测器"""
    
    def __init__(self):
        # 巨鲸等级阈值 (USD)
        self.whale_thresholds = {
            WhaleLevel.MEGA_WHALE: 50_000_000,
            WhaleLevel.LARGE_WHALE: 10_000_000,
            WhaleLevel.WHALE: 1_000_000,
            WhaleLevel.DOLPHIN: 100_000,
            WhaleLevel.FISH: 0
        }
        
        # 风险评分权重
        self.risk_weights = {
            'leverage': 0.3,
            'concentration': 0.25,
            'pnl_volatility': 0.2,
            'liquidation_risk': 0.25
        }
        
        # 活跃度评分权重
        self.activity_weights = {
            'position_count': 0.3,
            'trading_frequency': 0.4,
            'position_changes': 0.3
        }
    
    def classify_whale_level(self, total_value: float) -> WhaleLevel:
        """根据总仓位价值分类巨鲸等级"""
        for level, threshold in self.whale_thresholds.items():
            if total_value >= threshold:
                return level
        return WhaleLevel.FISH
    
    def calculate_leverage_score(self, positions: List[UserPosition]) -> Tuple[float, float, float]:
        """计算杠杆评分"""
        if not positions:
            return 0.0, 0.0, 0.0
        
        leverages = [pos.leverage for pos in positions if pos.leverage > 0]
        
        if not leverages:
            return 0.0, 0.0, 0.0
        
        avg_leverage = sum(leverages) / len(leverages)
        max_leverage = max(leverages)
        
        # 杠杆评分 (0-100)
        # 1x = 0分, 10x = 50分, 50x = 90分, 100x+ = 100分
        leverage_score = min(100, (avg_leverage - 1) * 2.5)
        
        return leverage_score, avg_leverage, max_leverage
    
    def calculate_concentration_score(self, positions: List[UserPosition]) -> Tuple[float, str, float]:
        """计算仓位集中度评分"""
        if not positions:
            return 0.0, "", 0.0
        
        # 按价值排序
        sorted_positions = sorted(positions, key=lambda x: x.position_value_usd, reverse=True)
        total_value = sum(pos.position_value_usd for pos in positions)
        
        if total_value <= 0:
            return 0.0, "", 0.0
        
        # 最大仓位占比
        largest_position = sorted_positions[0]
        largest_ratio = largest_position.position_value_usd / total_value
        
        # 前3大仓位占比
        top3_value = sum(pos.position_value_usd for pos in sorted_positions[:3])
        top3_ratio = top3_value / total_value
        
        # 集中度评分 (0-100)
        # 完全分散 = 0分, 单一仓位 = 100分
        concentration_score = largest_ratio * 60 + (top3_ratio - largest_ratio) * 40
        concentration_score = min(100, concentration_score * 100)
        
        return concentration_score, largest_position.coin, largest_position.position_value_usd
    
    def calculate_risk_score(self, positions: List[UserPosition], 
                           leverage_score: float, concentration_score: float) -> Tuple[float, RiskLevel]:
        """计算综合风险评分"""
        if not positions:
            return 0.0, RiskLevel.SAFE
        
        # 1. 杠杆风险
        leverage_risk = leverage_score
        
        # 2. 集中度风险
        concentration_risk = concentration_score
        
        # 3. PnL波动风险
        pnl_values = [pos.unrealized_pnl_percentage for pos in positions if pos.unrealized_pnl_percentage is not None]
        pnl_volatility = 0.0
        if pnl_values:
            pnl_std = math.sqrt(sum((x - sum(pnl_values)/len(pnl_values))**2 for x in pnl_values) / len(pnl_values))
            pnl_volatility = min(100, pnl_std * 2)  # 标准差转换为0-100分
        
        # 4. 清算风险
        liquidation_risk = 0.0
        for pos in positions:
            if hasattr(pos, 'liquidation_price') and pos.liquidation_price:
                if pos.mark_price > 0:
                    if pos.position_size > 0:  # 多头
                        risk_ratio = (pos.mark_price - pos.liquidation_price) / pos.mark_price
                    else:  # 空头
                        risk_ratio = (pos.liquidation_price - pos.mark_price) / pos.mark_price
                    
                    # 风险度转换为评分
                    if risk_ratio <= 0.05:  # 5%以内
                        liquidation_risk = max(liquidation_risk, 100)
                    elif risk_ratio <= 0.1:  # 10%以内
                        liquidation_risk = max(liquidation_risk, 80)
                    elif risk_ratio <= 0.2:  # 20%以内
                        liquidation_risk = max(liquidation_risk, 50)
        
        # 综合风险评分
        risk_score = (
            leverage_risk * self.risk_weights['leverage'] +
            concentration_risk * self.risk_weights['concentration'] +
            pnl_volatility * self.risk_weights['pnl_volatility'] +
            liquidation_risk * self.risk_weights['liquidation_risk']
        )
        
        # 风险等级分类
        if risk_score >= 80:
            risk_level = RiskLevel.EXTREME
        elif risk_score >= 60:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 40:
            risk_level = RiskLevel.MEDIUM
        elif risk_score >= 20:
            risk_level = RiskLevel.LOW
        else:
            risk_level = RiskLevel.SAFE
        
        return risk_score, risk_level
    
    def calculate_activity_score(self, position_count: int, 
                               historical_data: List[Dict] = None) -> float:
        """计算活跃度评分"""
        # 基础活跃度 (基于仓位数量)
        position_activity = min(100, position_count * 5)  # 20个仓位 = 100分
        
        # 交易频率活跃度 (需要历史数据)
        trading_frequency = 50.0  # 默认中等活跃度
        
        # 仓位变化活跃度 (需要历史数据)
        position_changes = 50.0  # 默认中等活跃度
        
        if historical_data:
            # TODO: 基于历史数据计算更精确的活跃度
            pass
        
        activity_score = (
            position_activity * self.activity_weights['position_count'] +
            trading_frequency * self.activity_weights['trading_frequency'] +
            position_changes * self.activity_weights['position_changes']
        )
        
        return activity_score
    
    def generate_tags(self, profile: WhaleProfile, positions: List[UserPosition]) -> List[str]:
        """生成巨鲸标签"""
        tags = []
        
        # 等级标签
        tags.append(profile.whale_level.value)
        
        # 风险标签
        if profile.risk_level in [RiskLevel.EXTREME, RiskLevel.HIGH]:
            tags.append("high_risk")
        elif profile.risk_level == RiskLevel.SAFE:
            tags.append("conservative")
        
        # 杠杆标签
        if profile.avg_leverage >= 20:
            tags.append("high_leverage")
        elif profile.avg_leverage <= 2:
            tags.append("low_leverage")
        
        # 集中度标签
        if profile.concentration_score >= 80:
            tags.append("concentrated")
        elif profile.concentration_score <= 30:
            tags.append("diversified")
        
        # PnL标签
        if profile.pnl_percentage >= 50:
            tags.append("big_winner")
        elif profile.pnl_percentage <= -20:
            tags.append("big_loser")
        elif abs(profile.pnl_percentage) <= 5:
            tags.append("stable")
        
        # 活跃度标签
        if profile.activity_score >= 80:
            tags.append("very_active")
        elif profile.activity_score <= 30:
            tags.append("inactive")
        
        # 仓位数量标签
        if profile.position_count >= 20:
            tags.append("multi_position")
        elif profile.position_count == 1:
            tags.append("single_position")
        
        # 币种标签
        if positions:
            coins = [pos.coin for pos in positions]
            coin_counts = {}
            for coin in coins:
                coin_counts[coin] = coin_counts.get(coin, 0) + 1
            
            # 主要交易币种
            main_coins = [coin for coin, count in coin_counts.items() if count >= 2]
            if main_coins:
                tags.extend([f"trades_{coin.lower()}" for coin in main_coins[:3]])
        
        return tags
    
    def analyze_whale(self, address: str, positions: List[UserPosition], 
                     historical_data: List[Dict] = None) -> WhaleProfile:
        """分析巨鲸，生成完整档案"""
        if not positions:
            # 返回空档案
            return WhaleProfile(
                address=address,
                whale_level=WhaleLevel.FISH,
                risk_level=RiskLevel.SAFE,
                total_position_value=0.0,
                position_count=0,
                total_pnl=0.0,
                pnl_percentage=0.0,
                leverage_score=0.0,
                concentration_score=0.0,
                activity_score=0.0,
                risk_score=0.0,
                confidence_score=0.0,
                largest_position_value=0.0,
                largest_position_coin="",
                avg_leverage=0.0,
                max_leverage=0.0,
                first_seen=datetime.now().isoformat(),
                last_update=datetime.now().isoformat(),
                tags=[]
            )
        
        # 基础计算
        total_value = sum(pos.position_value_usd for pos in positions)
        total_pnl = sum(pos.unrealized_pnl for pos in positions)
        pnl_percentage = (total_pnl / total_value * 100) if total_value > 0 else 0.0
        
        # 分类巨鲸等级
        whale_level = self.classify_whale_level(total_value)
        
        # 计算各项评分
        leverage_score, avg_leverage, max_leverage = self.calculate_leverage_score(positions)
        concentration_score, largest_coin, largest_value = self.calculate_concentration_score(positions)
        risk_score, risk_level = self.calculate_risk_score(positions, leverage_score, concentration_score)
        activity_score = self.calculate_activity_score(len(positions), historical_data)
        
        # 置信度评分 (基于数据完整性和一致性)
        confidence_score = 85.0  # 基础置信度
        if len(positions) >= 5:
            confidence_score += 10  # 多仓位提高置信度
        if total_value >= 1_000_000:
            confidence_score += 5   # 大资金提高置信度
        
        confidence_score = min(100, confidence_score)
        
        # 创建档案
        profile = WhaleProfile(
            address=address,
            whale_level=whale_level,
            risk_level=risk_level,
            total_position_value=total_value,
            position_count=len(positions),
            total_pnl=total_pnl,
            pnl_percentage=pnl_percentage,
            leverage_score=leverage_score,
            concentration_score=concentration_score,
            activity_score=activity_score,
            risk_score=risk_score,
            confidence_score=confidence_score,
            largest_position_value=largest_value,
            largest_position_coin=largest_coin,
            avg_leverage=avg_leverage,
            max_leverage=max_leverage,
            first_seen=datetime.now().isoformat(),
            last_update=datetime.now().isoformat(),
            tags=[]
        )
        
        # 生成标签
        profile.tags = self.generate_tags(profile, positions)
        
        return profile
    
    def filter_whales(self, profiles: List[WhaleProfile], 
                     min_value: float = None,
                     whale_levels: List[WhaleLevel] = None,
                     risk_levels: List[RiskLevel] = None,
                     tags: List[str] = None,
                     sort_by: str = "total_position_value") -> List[WhaleProfile]:
        """过滤和排序巨鲸"""
        filtered = profiles.copy()
        
        # 按价值过滤
        if min_value is not None:
            filtered = [p for p in filtered if p.total_position_value >= min_value]
        
        # 按等级过滤
        if whale_levels:
            filtered = [p for p in filtered if p.whale_level in whale_levels]
        
        # 按风险等级过滤
        if risk_levels:
            filtered = [p for p in filtered if p.risk_level in risk_levels]
        
        # 按标签过滤
        if tags:
            filtered = [p for p in filtered if any(tag in p.tags for tag in tags)]
        
        # 排序
        if sort_by == "total_position_value":
            filtered.sort(key=lambda x: x.total_position_value, reverse=True)
        elif sort_by == "total_pnl":
            filtered.sort(key=lambda x: x.total_pnl, reverse=True)
        elif sort_by == "risk_score":
            filtered.sort(key=lambda x: x.risk_score, reverse=True)
        elif sort_by == "activity_score":
            filtered.sort(key=lambda x: x.activity_score, reverse=True)
        
        return filtered
    
    def print_whale_profile(self, profile: WhaleProfile):
        """打印巨鲸档案"""
        print(f"\n🐋 巨鲸档案: {profile.address[:10]}...")
        print("=" * 60)
        
        # 基础信息
        level_emoji = {
            WhaleLevel.MEGA_WHALE: "🐋",
            WhaleLevel.LARGE_WHALE: "🐳", 
            WhaleLevel.WHALE: "🐋",
            WhaleLevel.DOLPHIN: "🐬",
            WhaleLevel.FISH: "🐟"
        }
        
        risk_emoji = {
            RiskLevel.EXTREME: "🔴",
            RiskLevel.HIGH: "🟠",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.LOW: "🟢",
            RiskLevel.SAFE: "🔵"
        }
        
        print(f"等级: {level_emoji[profile.whale_level]} {profile.whale_level.value.upper()}")
        print(f"风险: {risk_emoji[profile.risk_level]} {profile.risk_level.value.upper()}")
        print(f"总仓位价值: ${profile.total_position_value:,.2f}")
        print(f"仓位数量: {profile.position_count}")
        print(f"总PnL: ${profile.total_pnl:,.2f} ({profile.pnl_percentage:+.2f}%)")
        
        print(f"\n📊 评分:")
        print(f"  杠杆评分: {profile.leverage_score:.1f}/100 (平均: {profile.avg_leverage:.1f}x)")
        print(f"  集中度评分: {profile.concentration_score:.1f}/100")
        print(f"  活跃度评分: {profile.activity_score:.1f}/100")
        print(f"  风险评分: {profile.risk_score:.1f}/100")
        print(f"  置信度: {profile.confidence_score:.1f}/100")
        
        if profile.largest_position_coin:
            print(f"\n🎯 最大仓位: {profile.largest_position_coin} (${profile.largest_position_value:,.2f})")
        
        if profile.tags:
            print(f"\n🏷️ 标签: {', '.join(profile.tags)}")
        
        print(f"\n⏰ 最后更新: {profile.last_update[:19]}")


if __name__ == "__main__":
    # 测试巨鲸检测器
    detector = WhaleDetector()
    
    # 模拟仓位数据
    test_positions = [
        UserPosition(
            coin="BTC",
            position_size=10.5,
            entry_price=45000,
            mark_price=47000,
            position_value_usd=493500,
            unrealized_pnl=21000,
            unrealized_pnl_percentage=4.45,
            leverage=5.0,
            margin_mode="cross"
        ),
        UserPosition(
            coin="ETH", 
            position_size=-50.0,
            entry_price=3200,
            mark_price=3100,
            position_value_usd=155000,
            unrealized_pnl=5000,
            unrealized_pnl_percentage=3.33,
            leverage=3.0,
            margin_mode="isolated"
        )
    ]
    
    # 分析巨鲸
    profile = detector.analyze_whale("0x1234567890abcdef", test_positions)
    
    # 打印档案
    detector.print_whale_profile(profile)