#!/usr/bin/env python3
"""
批量巨鲸地址监控系统
支持同时监控多个巨鲸地址的仓位变化、PnL变化等
"""

import json
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from dataclasses import dataclass

from hyperliquid_api_client import HyperliquidAPIClient, UserPosition
from whale_detection import WhaleDetector, WhaleLevel, RiskLevel
from feishu_notifier import FeishuNotifier
from config_loader import load_config, HyperliquidConfig


@dataclass
class WhaleMonitorConfig:
    """监控配置"""
    check_interval_minutes: int = 10
    max_concurrent_checks: int = 5
    position_change_threshold: float = 0.05  # 5%
    pnl_alert_threshold: float = 10000.0  # $10,000
    save_history: bool = True
    # 飞书推送配置
    enable_feishu_notifications: bool = True
    feishu_webhook_url: str = ""
    feishu_alert_threshold: float = 50000.0  # $50,000 变化才推送
    feishu_batch_summary: bool = True  # 是否发送批量汇总
    

class AllWhalesMonitor:
    """批量巨鲸监控器"""
    
    def __init__(self, config: WhaleMonitorConfig = None):
        self.api_client = HyperliquidAPIClient()
        self.whale_detector = WhaleDetector()
        self.config = config or WhaleMonitorConfig()
        
        # 监控数据
        self.monitored_addresses: Dict[str, dict] = {}
        self.historical_data: Dict[str, List[dict]] = {}
        self.last_positions: Dict[str, List[UserPosition]] = {}
        
        # 线程锁
        self.data_lock = threading.Lock()
        
        # 初始化飞书推送器
        self.feishu_notifier = None
        if (self.config.enable_feishu_notifications and 
            self.config.feishu_webhook_url):
            try:
                self.feishu_notifier = FeishuNotifier(self.config.feishu_webhook_url)
                print("✅ 飞书推送器初始化成功")
            except Exception as e:
                print(f"❌ 飞书推送器初始化失败: {e}")
                self.feishu_notifier = None
        
        # 加载地址
        self.load_addresses()
        
    def load_addresses(self) -> None:
        """从配置文件加载所有需要监控的地址"""
        addresses = {}
        
        # 1. 从 whale_config.json 加载手动配置的地址
        try:
            with open('whale_config.json', 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                manual_addresses = config_data.get('manual_addresses', {})
                
                for addr, info in manual_addresses.items():
                    if info.get('is_active', True):
                        addresses[addr] = {
                            'source': 'manual',
                            'name': info.get('name', f'地址_{addr[:8]}...'),
                            'tags': info.get('tags', []),
                            'description': info.get('description', ''),
                            'added_time': info.get('added_time', ''),
                        }
                        
        except FileNotFoundError:
            print("⚠️  未找到 whale_config.json 文件")
        except Exception as e:
            print(f"❌ 加载 whale_config.json 失败: {e}")
            
        # 2. 从 whale_addresses.json 加载历史地址（只加载活跃的巨鲸）
        try:
            with open('whale_addresses.json', 'r', encoding='utf-8') as f:
                addresses_data = json.load(f)
                stored_addresses = addresses_data.get('addresses', {})
                
                for addr, info in stored_addresses.items():
                    # 只加载巨鲸级别的地址或有较大仓位的地址
                    if (info.get('is_whale', False) or 
                        info.get('max_position_value', 0) > 1000000):  # > $1M
                        
                        if addr not in addresses:  # 避免重复
                            addresses[addr] = {
                                'source': 'auto',
                                'name': f'巨鲸_{addr[:8]}...',
                                'tags': info.get('tags', []),
                                'description': f"最大仓位: ${info.get('max_position_value', 0):,.2f}",
                                'added_time': info.get('first_seen', ''),
                                'max_position_value': info.get('max_position_value', 0),
                                'is_whale': info.get('is_whale', False)
                            }
                            
        except FileNotFoundError:
            print("⚠️  未找到 whale_addresses.json 文件")
        except Exception as e:
            print(f"❌ 加载 whale_addresses.json 失败: {e}")
            
        self.monitored_addresses = addresses
        print(f"📊 已加载 {len(addresses)} 个地址进行监控")
        
        # 打印加载的地址信息
        manual_count = sum(1 for addr in addresses.values() if addr['source'] == 'manual')
        auto_count = sum(1 for addr in addresses.values() if addr['source'] == 'auto')
        print(f"   - 手动配置: {manual_count} 个")
        print(f"   - 自动发现: {auto_count} 个")
        
    def get_current_positions(self, address: str) -> Tuple[List[UserPosition], float, float]:
        """获取指定地址的当前仓位"""
        try:
            # 使用带实时价格的方法
            positions = self.api_client.get_user_positions_with_current_prices(address)
            
            total_value = 0.0
            total_pnl = 0.0
            
            for position in positions:
                total_value += abs(position.position_value_usd)
                total_pnl += position.unrealized_pnl
                
            return positions, total_value, total_pnl
            
        except Exception as e:
            print(f"❌ 获取地址 {address[:10]}... 仓位失败: {e}")
            return [], 0.0, 0.0
            
    def analyze_position_changes(self, address: str, current_positions: List[UserPosition]) -> List[str]:
        """分析仓位变化"""
        alerts = []
        
        if address not in self.last_positions:
            alerts.append("🆕 首次记录该地址仓位")
            self.last_positions[address] = current_positions
            return alerts
            
        last_positions = self.last_positions[address]
        
        # 比较仓位数量变化
        if len(current_positions) != len(last_positions):
            alerts.append(f"📊 仓位数量变化: {len(last_positions)} → {len(current_positions)}")
            
        # 比较总价值变化
        current_total = sum(abs(p.position_value_usd) for p in current_positions)
        last_total = sum(abs(p.position_value_usd) for p in last_positions)
        
        if last_total > 0:
            change_pct = (current_total - last_total) / last_total
            if abs(change_pct) > self.config.position_change_threshold:
                direction = "📈" if change_pct > 0 else "📉"
                alerts.append(f"{direction} 总仓位变化: {change_pct:.2%} (${current_total - last_total:,.2f})")
                
        # 比较PnL变化
        current_pnl = sum(p.unrealized_pnl for p in current_positions)
        last_pnl = sum(p.unrealized_pnl for p in last_positions)
        pnl_change = current_pnl - last_pnl
        
        if abs(pnl_change) > self.config.pnl_alert_threshold:
            direction = "💰" if pnl_change > 0 else "💸"
            alerts.append(f"{direction} PnL大幅变化: ${pnl_change:,.2f}")
            
        self.last_positions[address] = current_positions
        return alerts
        
    def check_single_address(self, address: str) -> Optional[dict]:
        """检查单个地址"""
        try:
            addr_info = self.monitored_addresses.get(address, {})
            positions, total_value, total_pnl = self.get_current_positions(address)
            
            if total_value == 0:
                return None
                
            # 分析鲸鱼等级和风险
            analysis = self.whale_detector.analyze_whale(address, positions)
            
            # 分析变化
            alerts = self.analyze_position_changes(address, positions)
            
            # 构建报告
            report = {
                'address': address,
                'name': addr_info.get('name', f'地址_{address[:8]}...'),
                'source': addr_info.get('source', 'unknown'),
                'timestamp': datetime.now().isoformat(),
                'total_position_value': total_value,
                'total_pnl': total_pnl,
                'position_count': len(positions),
                'whale_level': analysis.whale_level.value,
                'risk_level': analysis.risk_level.value,
                'confidence': analysis.confidence_score,
                'leverage_score': analysis.leverage_score,
                'concentration_score': analysis.concentration_score,
                'positions': [
                    {
                        'coin': pos.coin,
                        'side': "多头" if pos.position_size > 0 else "空头",
                        'size': abs(pos.position_size),
                        'entry_price': pos.entry_price,
                        'mark_price': pos.mark_price,
                        'liquidation_price': pos.liquidation_price,
                        'leverage': pos.leverage,
                        'position_value': pos.position_value_usd,
                        'unrealized_pnl': pos.unrealized_pnl,
                        'pnl_percentage': (pos.unrealized_pnl / abs(pos.position_value_usd) * 100) if pos.position_value_usd != 0 else 0
                    }
                    for pos in positions
                ],
                'alerts': alerts
            }
            
            # 检查是否需要发送飞书警报
            self._check_feishu_alert(report)
            
            return report
            
        except Exception as e:
            print(f"❌ 检查地址 {address[:10]}... 失败: {e}")
            return None
            
    def print_summary_report(self, reports: List[dict]) -> None:
        """打印汇总报告"""
        if not reports:
            print("📊 当前没有活跃的巨鲸仓位")
            return
            
        print("\n" + "="*100)
        print(f"🐋 批量巨鲸监控报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*100)
        
        # 统计信息
        total_addresses = len(reports)
        total_value = sum(r['total_position_value'] for r in reports)
        total_pnl = sum(r['total_pnl'] for r in reports)
        
        print(f"📊 监控统计:")
        print(f"   - 活跃地址: {total_addresses}")
        print(f"   - 总仓位价值: ${total_value:,.2f}")
        print(f"   - 总未实现PnL: ${total_pnl:,.2f} ({(total_pnl/total_value*100) if total_value > 0 else 0:.2f}%)")
        
        # 按价值排序
        reports.sort(key=lambda x: x['total_position_value'], reverse=True)
        
        print(f"\n🏆 TOP巨鲸排行:")
        for i, report in enumerate(reports[:10], 1):
            whale_emoji = "🐋" if report['whale_level'] == 'mega_whale' else "🐟" if report['whale_level'] == 'whale' else "🐠"
            risk_emoji = "🔴" if report['risk_level'] == 'high' else "🟡" if report['risk_level'] == 'medium' else "🟢"
            pnl_emoji = "📈" if report['total_pnl'] >= 0 else "📉"
            
            print(f"   {i:2d}. {whale_emoji} {report['name'][:20]:<20} "
                  f"${report['total_position_value']:>12,.0f} "
                  f"{pnl_emoji} ${report['total_pnl']:>10,.0f} "
                  f"{risk_emoji} {report['risk_level']}")
                  
        # 详细显示每个地址的仓位信息
        print(f"\n📋 详细仓位信息:")
        print("-" * 100)
        
        for report in reports:
            print(f"\n🏷️  {report['name']} ({report['address'][:10]}...)")
            print(f"   💰 总价值: ${report['total_position_value']:,.2f} | "
                  f"📊 PnL: ${report['total_pnl']:,.2f} ({(report['total_pnl']/report['total_position_value']*100) if report['total_position_value'] > 0 else 0:.2f}%) | "
                  f"🎯 风险: {report['risk_level']}")
            
            if report['positions']:
                print("   📈 仓位详情:")
                for pos in report['positions']:
                    side_emoji = "🟢" if pos['side'] == "多头" else "🔴"
                    pnl_emoji = "📈" if pos['unrealized_pnl'] >= 0 else "📉"
                    
                    # 计算爆仓线距离
                    liquidation_distance = ""
                    if pos.get('liquidation_price') and pos.get('mark_price'):
                        liq_price = pos['liquidation_price']
                        mark_price = pos['mark_price']
                        if liq_price > 0:
                            distance_pct = abs(mark_price - liq_price) / mark_price * 100
                            liquidation_distance = f"💥 爆仓线: ${liq_price:,.2f} ({distance_pct:.1f}%)"
                    
                    print(f"      {side_emoji} {pos['side']} {pos['coin']:<8} | "
                          f"💵 价值: ${pos['position_value']:>10,.0f} | "
                          f"📏 数量: {pos['size']:>10.4f} | "
                          f"🎯 杠杆: {pos.get('leverage', 'N/A'):>4}x")
                    
                    print(f"         📊 开仓价: ${pos.get('entry_price', 0):>8.2f} | "
                          f"📍 标记价: ${pos.get('mark_price', 0):>8.2f} | "
                          f"{pnl_emoji} PnL: ${pos['unrealized_pnl']:>8,.0f} ({pos['pnl_percentage']:>5.1f}%)")
                    
                    if liquidation_distance:
                        print(f"         {liquidation_distance}")
                    
                    print()
            else:
                print("   ⚪ 暂无活跃仓位")
                  
        # 显示有警报的地址
        alert_reports = [r for r in reports if r['alerts']]
        if alert_reports:
            print(f"\n🚨 变化警报 ({len(alert_reports)} 个地址):")
            for report in alert_reports:
                print(f"\n📍 {report['name']} ({report['address'][:10]}...)")
                for alert in report['alerts']:
                    print(f"   {alert}")
                    
    def save_historical_data(self, reports: List[dict]) -> None:
        """保存历史数据"""
        if not self.config.save_history or not reports:
            return
            
        try:
            timestamp = datetime.now().strftime('%Y%m%d')
            filename = f"whale_monitor_batch_{timestamp}.json"
            
            # 准备保存的数据
            save_data = {
                'timestamp': datetime.now().isoformat(),
                'total_addresses': len(reports),
                'total_monitored': len(self.monitored_addresses),
                'summary': {
                    'total_value': sum(r['total_position_value'] for r in reports),
                    'total_pnl': sum(r['total_pnl'] for r in reports),
                    'active_addresses': len(reports)
                },
                'reports': reports
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
                
            print(f"💾 批量监控数据已保存到: {filename}")
            
        except Exception as e:
            print(f"❌ 保存历史数据失败: {e}")
            
    def _check_feishu_alert(self, report: dict) -> None:
        """检查是否需要发送飞书警报"""
        try:
            # 检查是否有重要变化
            should_alert = False
            alert_reasons = []
            
            # 1. 检查单个仓位是否达到阈值（1千万美元）
            large_positions = []
            for position in report['positions']:
                position_value = abs(position['position_value'])
                if position_value >= self.config.feishu_alert_threshold:
                    should_alert = True
                    large_positions.append({
                        'symbol': position['coin'],
                        'value': position_value,
                        'side': position['side']
                    })
                    alert_reasons.append(f"大额单仓: {position['coin']} ${position_value:,.0f}")
            
            # 如果没有单个仓位达到阈值，不进行推送
            if not should_alert:
                return
                
            # 2. 检查PnL变化（仅在有大额仓位时才检查）
            if abs(report['total_pnl']) > self.config.feishu_alert_threshold * 0.1:  # PnL阈值设为仓位阈值的10%
                alert_reasons.append(f"大额PnL: ${report['total_pnl']:,.0f}")
                
            # 3. 检查是否有警报
            if report['alerts']:
                alert_reasons.extend(report['alerts'][:2])  # 最多2个警报
                
            # 4. 检查巨鲸等级
            if report['whale_level'] in ['mega_whale', 'super_whale']:
                alert_reasons.append(f"巨鲸等级: {report['whale_level']}")
            
            # 始终显示模拟推送消息（无论是否启用飞书推送）
            self._print_feishu_simulation(report, alert_reasons)
            
            # 如果启用了飞书推送，则实际发送
            if self.feishu_notifier:
                success = self.feishu_notifier.send_whale_alert(
                    whale_name=report['name'],
                    address=report['address'],
                    total_value=report['total_position_value'],
                    total_pnl=report['total_pnl'],
                    positions=report['positions'],
                    alerts=alert_reasons
                )
                
                if success:
                    large_pos_info = ", ".join([f"{pos['symbol']}(${pos['value']:,.0f})" for pos in large_positions[:3]])
                    print(f"✅ 飞书警报发送成功: {report['name']} - 大额仓位: {large_pos_info}")
                else:
                    print(f"❌ 飞书警报发送失败: {report['name']}")
            else:
                print(f"📱 飞书推送已禁用，仅显示模拟消息")
                
        except Exception as e:
            print(f"❌ 飞书警报检查失败: {e}")
    
    def _print_feishu_simulation(self, report: dict, alert_reasons: List[str]) -> None:
        """打印飞书推送的模拟消息"""
        print("\n" + "="*80)
        print("📱 飞书推送模拟消息")
        print("="*80)
        print(f"🏷️  巨鲸名称: {report['name']}")
        print(f"📍 地址: {report['address']}")
        print(f"💰 总仓位价值: ${report['total_position_value']:,.2f}")
        print(f"📊 总PnL: ${report['total_pnl']:,.2f}")
        print(f"🚨 警报原因: {', '.join(alert_reasons)}")
        print("\n📊 仓位详情:")
        if report['positions']:
            # 只显示价值最大的一个仓位
            largest_position = max(report['positions'], key=lambda x: abs(x['position_value']))
            side_emoji = "🟢" if largest_position['side'] == "多头" else "🔴"
            pnl_emoji = "📈" if largest_position['unrealized_pnl'] >= 0 else "📉"
            print(f"   {side_emoji} {largest_position['side']} {largest_position['coin']}")
            print(f"      💵 价值: ${largest_position['position_value']:,.0f}")
            print(f"      📏 数量: {largest_position['size']:,.4f}")
            print(f"      🎯 杠杆: {largest_position.get('leverage', 'N/A')}x")
            print(f"      {pnl_emoji} PnL: ${largest_position['unrealized_pnl']:,.0f} ({largest_position['pnl_percentage']:.1f}%)")
            print()
        else:
            print("   ⚪ 暂无活跃仓位")
        print("="*80)
            

            
    def run_batch_check(self) -> List[dict]:
        """执行批量检查"""
        print(f"🔍 开始批量检查 {len(self.monitored_addresses)} 个地址...")
        
        reports = []
        
        # 使用线程池并发检查
        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_checks) as executor:
            # 提交所有任务
            future_to_address = {
                executor.submit(self.check_single_address, address): address 
                for address in self.monitored_addresses.keys()
            }
            
            # 收集结果
            for future in as_completed(future_to_address):
                address = future_to_address[future]
                try:
                    result = future.result()
                    if result:
                        reports.append(result)
                        print(f"✅ {address[:10]}... - ${result['total_position_value']:,.0f}")
                    else:
                        print(f"⚪ {address[:10]}... - 无活跃仓位")
                except Exception as e:
                    print(f"❌ {address[:10]}... - 检查失败: {e}")
                    
        return reports
        
    def start_monitoring(self) -> None:
        """开始持续监控"""
        print(f"🔄 开始批量监控 {len(self.monitored_addresses)} 个巨鲸地址")
        print(f"⏱️  监控间隔: {self.config.check_interval_minutes} 分钟")
        print(f"🔧 并发数: {self.config.max_concurrent_checks}")
        print("按 Ctrl+C 停止监控\n")
        
        try:
            while True:
                start_time = time.time()
                
                # 执行批量检查
                reports = self.run_batch_check()
                
                # 显示报告
                self.print_summary_report(reports)
                
                # 保存数据
                self.save_historical_data(reports)
                
                # 发送飞书批量汇总（每次监控都发送）
                # if reports:
                #     self._send_feishu_batch_summary(reports)
                
                # 计算耗时
                elapsed = time.time() - start_time
                print(f"\n⏱️  本轮检查耗时: {elapsed:.1f}秒")
                
                # 等待下次检查
                print(f"💤 等待 {self.config.check_interval_minutes} 分钟...")
                time.sleep(self.config.check_interval_minutes * 60)
                
        except KeyboardInterrupt:
            print("\n🛑 监控已停止")
            
            # 最后保存一次数据
            if hasattr(self, '_last_reports'):
                self.save_historical_data(self._last_reports)


def main():
    """主函数"""
    print("🐋 启动巨鲸监控系统...")
    
    try:
        # 加载配置
        app_config = load_config()
        print("✅ 配置加载成功")
        
        # 创建监控器配置
        config = WhaleMonitorConfig()
        
        # 从配置文件设置飞书推送参数
        config.feishu_webhook_url = app_config.feishu.webhook_url
        config.enable_feishu_notifications = app_config.feishu.enable_notifications
        config.feishu_alert_threshold = app_config.feishu.alert_threshold
        config.feishu_batch_summary = app_config.feishu.batch_summary
        
        # 设置监控参数
        config.check_interval_minutes = app_config.monitoring.check_interval_minutes
        config.max_concurrent_checks = app_config.monitoring.max_concurrent_checks
        config.position_change_threshold = app_config.monitoring.position_change_threshold
        config.pnl_alert_threshold = app_config.monitoring.pnl_alert_threshold
        config.save_history = app_config.monitoring.save_history
        
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        print("请确保 config.json 文件存在且格式正确")
        return
    
    # 询问是否启用飞书推送
    try:
        feishu_choice = input(f"\n是否启用飞书推送? (当前配置: {'启用' if config.enable_feishu_notifications else '禁用'}) (y/N): ").lower().strip()
        if feishu_choice in ['y', 'yes', '是']:
            config.enable_feishu_notifications = True
            print("✅ 飞书推送已启用")
        else:
            config.enable_feishu_notifications = False
            print("⚪ 飞书推送已禁用")
    except KeyboardInterrupt:
        print("\n👋 监控结束")
        return
    
    monitor = AllWhalesMonitor(config)
    
    # 显示实际配置阈值
    print("\n" + "="*60)
    print("📊 当前监控配置阈值")
    print("="*60)
    print(f"🚨 飞书推送阈值:")
    print(f"   💰 单仓位推送阈值: ${config.feishu_alert_threshold:,.0f}")
    print(f"   📊 PnL推送阈值: ${config.feishu_alert_threshold * 0.1:,.0f} (单仓位阈值的10%)")
    print(f"   🔔 推送状态: {'✅ 启用' if config.enable_feishu_notifications else '❌ 禁用'}")
    
    print(f"\n🔍 监控检测阈值:")
    print(f"   📈 仓位变化阈值: {config.position_change_threshold * 100:.1f}%")
    print(f"   💸 PnL警报阈值: ${config.pnl_alert_threshold:,.0f}")
    
    print(f"\n🐋 巨鲸等级阈值:")
    # 从whale_detector获取阈值
    whale_config = monitor.whale_detector
    if hasattr(whale_config, 'min_position_value'):
        print(f"   🐟 最小仓位价值: ${whale_config.min_position_value:,.0f}")
    if hasattr(whale_config, 'mega_whale_threshold'):
        print(f"   🐋 超级巨鲸阈值: ${whale_config.mega_whale_threshold:,.0f}")
    if hasattr(whale_config, 'super_whale_threshold'):
        print(f"   🦈 终极巨鲸阈值: ${whale_config.super_whale_threshold:,.0f}")
    
    print(f"\n⚙️  系统运行参数:")
    print(f"   ⏰ 检查间隔: {config.check_interval_minutes} 分钟")
    print(f"   🔄 最大并发检查数: {config.max_concurrent_checks} 个地址")
    print("="*60)
    
    if not monitor.monitored_addresses:
        print("❌ 没有找到需要监控的地址，请检查配置文件")
        return
        
    # 执行初始检查
    print("🔍 执行初始批量检查...")
    reports = monitor.run_batch_check()
    monitor.print_summary_report(reports)
    
    if reports:
        monitor.save_historical_data(reports)
        # 发送飞书批量汇总
        # monitor._send_feishu_batch_summary(reports)
        
    # 询问是否开始持续监控
    try:
        start_continuous = input("\n是否开始持续监控? (y/N): ").lower().strip()
        if start_continuous in ['y', 'yes', '是']:
            
            # 询问监控间隔
            try:
                interval = input(f"监控间隔(分钟，默认{config.check_interval_minutes}): ").strip()
                if interval:
                    config.check_interval_minutes = int(interval)
            except ValueError:
                print("使用默认间隔")
                
            # 询问并发数
            try:
                concurrent = input(f"并发检查数(默认{config.max_concurrent_checks}): ").strip()
                if concurrent:
                    config.max_concurrent_checks = int(concurrent)
            except ValueError:
                print("使用默认并发数")
                
            monitor.config = config
            monitor.start_monitoring()
        else:
            print("👋 监控结束")
            
    except KeyboardInterrupt:
        print("\n👋 监控结束")


if __name__ == "__main__":
    main()