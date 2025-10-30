#!/usr/bin/env python3
"""
Alpha Binance 主监控程序
整合配置加载、网页监控和通知功能
"""

import time
import signal
import sys
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from config_loader import load_config, MonitorConfig
from web_monitor import WebMonitor, MonitorResult
from error_handler import (
    init_error_handler, get_error_handler, ErrorType, ErrorLevel,
    log_info, log_warning, log_error, handle_exception
)


class AlphaMonitor:
    """Alpha Binance 主监控器"""
    
    def __init__(self, config: MonitorConfig):
        """
        初始化监控器
        
        Args:
            config: 监控配置
        """
        self.config = config
        self.web_monitor = WebMonitor(
            base_url=config.monitor_url,
            timeout=config.timeout,
            max_retries=config.max_retries
        )
        self.running = False
        self.check_count = 0
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 日志文件路径
        self.log_dir = Path(__file__).parent / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        # 初始化错误处理器
        self.error_handler = init_error_handler(self.log_dir, config.enable_logging)
        
        log_info("Alpha Binance 监控器初始化完成")
        
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        log_info(f"接收到信号 {signum}，正在停止监控...")
        self.running = False
    
    def _log(self, message: str, level: str = "INFO"):
        """
        记录日志
        
        Args:
            message: 日志消息
            level: 日志级别
        """
        if level == "ERROR":
            log_error(message)
        elif level == "WARNING":
            log_warning(message)
        else:
            log_info(message)
    
    def _print_and_log(self, message: str, level: str = "INFO"):
        """打印并记录日志"""
        # 打印到控制台
        if level == "ERROR":
            print(f"❌ {message}")
        elif level == "WARNING":
            print(f"⚠️ {message}")
        else:
            print(f"ℹ️ {message}")
        
        # 记录到日志
        self._log_message(message, level)
    
    def _save_result(self, result: MonitorResult):
        """保存监控结果到文件"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result_file = self.log_dir / f"result_{timestamp}.json"
            
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            
            log_info(f"监控结果已保存到: {result_file}")
            
        except Exception as e:
            handle_exception(e, ErrorType.FILE_ERROR, "保存监控结果失败")
    
    def _format_changes(self, changes: list) -> str:
        """
        格式化变化信息
        
        Args:
            changes: 变化列表
            
        Returns:
            格式化的变化信息
        """
        if not changes:
            return "无变化"
        
        formatted = []
        for change in changes[:10]:  # 最多显示10个变化
            formatted.append(f"  • {change}")
        
        if len(changes) > 10:
            formatted.append(f"  • ... 还有 {len(changes) - 10} 个变化")
        
        return "\n".join(formatted)
    
    def _print_summary(self, result: MonitorResult):
        """
        打印监控摘要
        
        Args:
            result: 监控结果
        """
        summary = self.web_monitor.get_summary()
        
        print("\n" + "="*60)
        print(f"📊 监控摘要 (第 {self.check_count} 次检查)")
        print("="*60)
        print(f"🕐 检查时间: {datetime.fromtimestamp(result.timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📋 空投总数: {summary['total_airdrops']}")
        print(f"   ⏳ 进行中: {summary['active_airdrops']}")
        print(f"   ✅ 已完成: {summary['completed_airdrops']}")
        print(f"   📈 现货上市: {summary['spot_listed']}")
        print(f"   📊 合约上市: {summary['futures_listed']}")
        print(f"💰 价格数据: {summary['total_prices']} 个代币")
        print(f"🔄 变化数量: {len(result.changes)}")
        
        if result.changes:
            print(f"\n📝 检测到的变化:")
            print(self._format_changes(result.changes))
        
        print("="*60)
    
    def _print_detailed_info(self, result: MonitorResult):
        """
        打印详细信息
        
        Args:
            result: 监控结果
        """
        if not result.airdrops:
            return
        
        print(f"\n📋 空投详情 (共 {len(result.airdrops)} 个):")
        print("-" * 80)
        
        # 按日期排序
        sorted_airdrops = sorted(result.airdrops, key=lambda x: (x.date, x.time))
        
        for i, airdrop in enumerate(sorted_airdrops, 1):
            status_emoji = "✅" if airdrop.completed else "⏳"
            type_emoji = "🎯" if airdrop.type == "tge" else "🎁"
            
            print(f"{i:2d}. {status_emoji} {type_emoji} {airdrop.name} ({airdrop.token})")
            print(f"     📅 时间: {airdrop.date} {airdrop.time}")
            print(f"     📊 状态: {airdrop.status} | 类型: {airdrop.type} | 积分: {airdrop.points}")
            print(f"     💰 数量: {airdrop.amount}")
            
            if airdrop.target_bnb and airdrop.actual_bnb:
                try:
                    target = float(airdrop.target_bnb)
                    actual = float(airdrop.actual_bnb)
                    ratio = actual / target if target > 0 else 0
                    print(f"     🎯 BNB: 目标 {target:.1f} | 实际 {actual:.1f} | 倍数 {ratio:.1f}x")
                except:
                    print(f"     🎯 BNB: 目标 {airdrop.target_bnb} | 实际 {airdrop.actual_bnb}")
            
            # 显示价格信息
            if airdrop.token in result.prices:
                price_info = result.prices[airdrop.token]
                if price_info.dex_price > 0:
                    print(f"     💵 价格: ${price_info.dex_price:.6f}")
            
            print()
    
    def run_once(self) -> bool:
        """
        执行一次监控检查
        
        Returns:
            是否成功
        """
        self.check_count += 1
        
        try:
            # 执行监控
            result = self.web_monitor.monitor()
            
            if result.success:
                # 打印摘要
                self._print_summary(result)
                
                # 如果有变化，记录详细日志
                if result.changes:
                    self._print_and_log(f"检测到 {len(result.changes)} 个变化:", "INFO")
                    for change in result.changes:
                        self._print_and_log(f"  {change}", "INFO")
                
                # 保存结果
                self._save_result(result)
                
                return True
            else:
                self._print_and_log(f"❌ 监控失败: {result.error_message}", "ERROR")
                return False
                
        except Exception as e:
            self._print_and_log(f"❌ 监控异常: {e}", "ERROR")
            return False
    
    def run_continuous(self):
        """持续监控模式"""
        self.running = True
        self._print_and_log("🚀 开始持续监控模式", "INFO")
        self._print_and_log(f"⏱️  检查间隔: {self.config.check_interval} 秒", "INFO")
        
        while self.running:
            try:
                success = self.run_once()
                
                if not success:
                    self._print_and_log("⚠️  本次检查失败，将在下次间隔后重试", "WARNING")
                
                # 等待下次检查
                if self.running:
                    self._print_and_log(f"😴 等待 {self.config.check_interval} 秒后进行下次检查...", "INFO")
                    
                    # 分段睡眠，以便能够响应停止信号
                    remaining = self.config.check_interval
                    while remaining > 0 and self.running:
                        sleep_time = min(5, remaining)  # 每5秒检查一次停止信号
                        time.sleep(sleep_time)
                        remaining -= sleep_time
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self._print_and_log(f"❌ 监控循环异常: {e}", "ERROR")
                time.sleep(10)  # 异常后等待10秒再继续
        
        self._print_and_log("🛑 监控已停止", "INFO")
    
    def run_interactive(self):
        """交互式监控模式"""
        self._print_and_log("🎮 进入交互式监控模式", "INFO")
        
        while True:
            try:
                print("\n" + "="*50)
                print("🎮 Alpha Binance 监控器")
                print("="*50)
                print("1. 执行一次检查")
                print("2. 显示详细信息")
                print("3. 开始持续监控")
                print("4. 查看配置")
                print("5. 退出")
                print("-" * 50)
                
                choice = input("请选择操作 (1-5): ").strip()
                
                if choice == '1':
                    print("\n🔍 执行监控检查...")
                    self.run_once()
                
                elif choice == '2':
                    print("\n🔍 获取详细信息...")
                    result = self.web_monitor.monitor()
                    if result.success:
                        self._print_detailed_info(result)
                    else:
                        print(f"❌ 获取数据失败: {result.error_message}")
                
                elif choice == '3':
                    self.run_continuous()
                    break
                
                elif choice == '4':
                    print("\n📋 当前配置:")
                    print(f"   🌐 监控URL: {self.config.monitor_url}")
                    print(f"   ⏱️  检查间隔: {self.config.check_interval} 秒")
                    print(f"   ⏰ 请求超时: {self.config.timeout} 秒")
                    print(f"   🔄 最大重试: {self.config.max_retries} 次")
                    print(f"   📝 启用日志: {'是' if self.config.enable_logging else '否'}")
                
                elif choice == '5':
                    print("👋 再见!")
                    break
                
                else:
                    print("❌ 无效选择，请重试")
                    
            except KeyboardInterrupt:
                print("\n👋 再见!")
                break
            except Exception as e:
                print(f"❌ 操作异常: {e}")


def main():
    """主函数"""
    print("🚀 Alpha Binance 监控器启动中...")
    
    try:
        # 加载配置
        config = load_config()
        print("✅ 配置加载成功")
        
        # 创建监控器
        monitor = AlphaMonitor(config)
        
        # 检查命令行参数
        if len(sys.argv) > 1:
            mode = sys.argv[1].lower()
            if mode == 'once':
                print("🔍 单次检查模式")
                monitor.run_once()
            elif mode == 'continuous':
                print("🔄 持续监控模式")
                monitor.run_continuous()
            else:
                print(f"❌ 未知模式: {mode}")
                print("使用方法: python monitor.py [once|continuous]")
        else:
            # 默认交互式模式
            monitor.run_interactive()
            
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()