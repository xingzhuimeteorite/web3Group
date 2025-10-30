#!/usr/bin/env python3
"""
时间周期管理器
功能：
1. 每小时调用web_catch.py获取空投信息
2. 每分钟检查任务表，进行3小时前和1小时前的提醒
3. 管理空投任务数据结构
"""

import time
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from web_catch import WebCatch, AirdropInfo
from airdrop_notifier import AirdropNotifier
from config_loader import load_config


@dataclass
class ReminderStatus:
    """提醒状态"""
    three_hours_sent: bool = False    # 3小时前提醒是否已发送
    one_hour_sent: bool = False       # 1小时前提醒是否已发送
    
    def to_dict(self):
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


@dataclass
class AirdropTask:
    """空投任务"""
    airdrop_info: AirdropInfo
    reminder_status: ReminderStatus
    created_at: str
    updated_at: str
    
    def to_dict(self):
        return {
            'airdrop_info': asdict(self.airdrop_info),
            'reminder_status': self.reminder_status.to_dict(),
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        airdrop_info = AirdropInfo(**data['airdrop_info'])
        reminder_status = ReminderStatus.from_dict(data['reminder_status'])
        return cls(
            airdrop_info=airdrop_info,
            reminder_status=reminder_status,
            created_at=data['created_at'],
            updated_at=data['updated_at']
        )


class TaskStorage:
    """任务存储管理器"""
    
    def __init__(self, storage_file: str = "airdrop_tasks.json"):
        self.storage_file = Path(storage_file)
        self.tasks: Dict[str, AirdropTask] = {}
        self.load_tasks()
    
    def load_tasks(self):
        """加载任务数据"""
        if self.storage_file.exists():
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for task_id, task_data in data.items():
                        self.tasks[task_id] = AirdropTask.from_dict(task_data)
                print(f"📂 加载了 {len(self.tasks)} 个任务")
            except Exception as e:
                print(f"❌ 加载任务失败: {e}")
                self.tasks = {}
    
    def save_tasks(self):
        """保存任务数据"""
        try:
            data = {task_id: task.to_dict() for task_id, task in self.tasks.items()}
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 保存了 {len(self.tasks)} 个任务")
        except Exception as e:
            print(f"❌ 保存任务失败: {e}")
    
    def add_or_update_task(self, airdrop: AirdropInfo) -> str:
        """添加或更新任务"""
        task_id = f"{airdrop.token}_{airdrop.date}_{airdrop.time}"
        current_time = datetime.now().isoformat()
        
        if task_id in self.tasks:
            # 更新现有任务
            self.tasks[task_id].airdrop_info = airdrop
            self.tasks[task_id].updated_at = current_time
            print(f"🔄 更新任务: {airdrop.name} ({airdrop.token})")
        else:
            # 创建新任务
            self.tasks[task_id] = AirdropTask(
                airdrop_info=airdrop,
                reminder_status=ReminderStatus(),
                created_at=current_time,
                updated_at=current_time
            )
            print(f"➕ 新增任务: {airdrop.name} ({airdrop.token})")
        
        return task_id
    
    def get_tasks_need_reminder(self) -> List[tuple]:
        """获取需要提醒的任务"""
        now = datetime.now()
        need_reminder = []
        
        for task_id, task in self.tasks.items():
            airdrop = task.airdrop_info
            
            # 跳过没有完整时间信息的任务
            if not airdrop.date or not airdrop.time:
                continue
            
            try:
                # 解析空投时间
                airdrop_datetime = datetime.strptime(f"{airdrop.date} {airdrop.time}", "%Y-%m-%d %H:%M")
                
                # 计算时间差
                time_diff = airdrop_datetime - now
                hours_left = time_diff.total_seconds() / 3600
                
                # 检查是否需要3小时前提醒
                if 2.5 <= hours_left <= 3.5 and not task.reminder_status.three_hours_sent:
                    need_reminder.append((task_id, task, "3小时前"))
                
                # 检查是否需要1小时前提醒
                elif 0.5 <= hours_left <= 1.5 and not task.reminder_status.one_hour_sent:
                    need_reminder.append((task_id, task, "1小时前"))
                    
            except ValueError as e:
                print(f"⚠️ 解析时间失败: {airdrop.date} {airdrop.time} - {e}")
                continue
        
        return need_reminder
    
    def mark_reminder_sent(self, task_id: str, reminder_type: str):
        """标记提醒已发送"""
        if task_id in self.tasks:
            if reminder_type == "3小时前":
                self.tasks[task_id].reminder_status.three_hours_sent = True
            elif reminder_type == "1小时前":
                self.tasks[task_id].reminder_status.one_hour_sent = True
            
            self.tasks[task_id].updated_at = datetime.now().isoformat()
            print(f"✅ 标记 {reminder_type} 提醒已发送: {self.tasks[task_id].airdrop_info.name}")
    
    def cleanup_old_tasks(self, days: int = 7):
        """清理过期任务"""
        now = datetime.now()
        to_remove = []
        
        for task_id, task in self.tasks.items():
            airdrop = task.airdrop_info
            
            if not airdrop.date:
                continue
                
            try:
                airdrop_date = datetime.strptime(airdrop.date, "%Y-%m-%d")
                if (now - airdrop_date).days > days:
                    to_remove.append(task_id)
            except ValueError:
                continue
        
        for task_id in to_remove:
            del self.tasks[task_id]
            print(f"🗑️ 清理过期任务: {task_id}")
        
        if to_remove:
            self.save_tasks()


class AirdropScheduler:
    """空投调度器"""
    
    def __init__(self, storage_file: str = "airdrop_tasks.json", test_mode: bool = False):
        """
        初始化调度器
        
        Args:
            storage_file: 任务存储文件路径
            test_mode: 测试模式，为True时禁用飞书通知
        """
        self.storage_file = storage_file
        self.test_mode = test_mode
        self.web_catch = WebCatch()
        self.task_storage = TaskStorage(storage_file)
        
        # 初始化飞书通知器
        self.notifier = None
        if not test_mode:
            try:
                config = load_config()
                if config.feishu_webhook_url:
                    self.notifier = AirdropNotifier(config.feishu_webhook_url)
                    print("✅ 飞书通知器初始化成功")
                else:
                    print("⚠️ 未配置飞书webhook，通知功能将被禁用")
            except Exception as e:
                print(f"❌ 飞书通知器初始化失败: {e}")
                self.notifier = None
        else:
            print("🧪 测试模式：飞书通知已禁用")
        
        # 线程控制
        self.running = False
        self.fetch_thread = None
        self.reminder_thread = None
        self.thread_lock = threading.Lock()
    
    def fetch_and_update_airdrops(self):
        """抓取并更新空投信息"""
        print(f"🔄 [{datetime.now().strftime('%H:%M:%S')}] 开始抓取空投信息...")
        
        try:
            airdrops = self.web_catch.fetch_airdrops()
            
            if not airdrops:
                print("⚠️ 未获取到空投信息")
                return
            
            # 更新任务表
            for airdrop in airdrops:
                self.task_storage.add_or_update_task(airdrop)
            
            # 保存任务
            self.task_storage.save_tasks()
            
            print(f"✅ 更新完成，共处理 {len(airdrops)} 个空投")
            
        except Exception as e:
            print(f"❌ 抓取空投信息失败: {e}")
    
    def send_daily_summary(self):
        """发送每日空投汇总"""
        if not self.notifier:
            return
            
        try:
            # 获取今日和未来的空投
            today_airdrops = []
            upcoming_airdrops = []
            
            for task in self.task_storage.tasks.values():
                airdrop = task.airdrop_info
                airdrop_date = datetime.strptime(airdrop.date, '%Y-%m-%d').date()
                today = datetime.now().date()
                
                if airdrop_date == today:
                    today_airdrops.append(airdrop)
                elif airdrop_date > today and airdrop_date <= today + timedelta(days=7):
                    upcoming_airdrops.append(airdrop)
            
            # 发送飞书通知
            if not self.notifier:
                print("📱 飞书通知未启用，跳过每日汇总")
                return
                
            if self.test_mode:
                print("🧪 测试模式：跳过每日汇总发送")
                return
            # 按时间排序
            today_airdrops.sort(key=lambda x: x.time)
            upcoming_airdrops.sort(key=lambda x: (x.date, x.time))
            # 发送汇总
            success = self.notifier.send_daily_summary(today_airdrops, upcoming_airdrops)
            if success:
                print("✅ 每日汇总发送成功")
            else:
                print("❌ 每日汇总发送失败")
                
        except Exception as e:
            print(f"❌ 发送每日汇总失败: {e}")
    
    def check_reminders(self):
        """检查并发送提醒"""
        try:
            need_reminder = self.task_storage.get_tasks_need_reminder()
            
            if not need_reminder:
                return
            
            print(f"🔔 [{datetime.now().strftime('%H:%M:%S')}] 发现 {len(need_reminder)} 个需要提醒的任务")
            
            for task_id, task, reminder_type in need_reminder:
                airdrop = task.airdrop_info
                
                # 控制台提醒信息
                print(f"🚨 {reminder_type}提醒: {airdrop.name} ({airdrop.token})")
                print(f"   📅 时间: {airdrop.date} {airdrop.time}")
                print(f"   🎯 积分: {airdrop.points}")
                print(f"   💰 数量: {airdrop.amount}")
                
                # 发送飞书通知
                if self.notifier and not self.test_mode:
                    try:
                        success = self.notifier.send_airdrop_reminder(airdrop, reminder_type)
                        if success:
                            print(f"✅ 飞书提醒发送成功: {airdrop.name}")
                        else:
                            print(f"❌ 飞书提醒发送失败: {airdrop.name}")
                    except Exception as e:
                        print(f"❌ 飞书提醒发送异常: {e}")
                elif self.test_mode:
                    print("🧪 测试模式：跳过飞书通知")
                else:
                    print("📱 飞书通知未启用")
                
                print()
                
                # 标记提醒已发送
                self.task_storage.mark_reminder_sent(task_id, reminder_type)
            
            # 保存更新
            self.task_storage.save_tasks()
            
        except Exception as e:
            print(f"❌ 检查提醒失败: {e}")
            # 发送错误通知
            if self.notifier:
                try:
                    self.notifier.send_error_alert("提醒检查失败", str(e), "调度器提醒功能")
                except:
                    pass
    
    def hourly_task(self):
        """每小时执行的任务"""
        while self.running:
            try:
                self.fetch_and_update_airdrops()
                # 清理过期任务
                self.task_storage.cleanup_old_tasks()
                # 等待1小时
                time.sleep(3600)  # 3600秒 = 1小时
                
            except Exception as e:
                print(f"❌ 每小时任务执行失败: {e}")
                time.sleep(60)  # 出错时等待1分钟后重试
    
    def minute_task(self):
        """每分钟执行的任务"""
        while self.running:
            try:
                self.check_reminders()
                # 等待1分钟
                time.sleep(60)  # 60秒 = 1分钟
                
            except Exception as e:
                print(f"❌ 每分钟任务执行失败: {e}")
                time.sleep(10)  # 出错时等待10秒后重试
    
    def start(self):
        """启动调度器"""
        if self.running:
            print("⚠️ 调度器已经在运行中")
            return
        self.running = True
        print("🚀 启动空投调度器...")
        # 立即执行一次抓取
        self.fetch_and_update_airdrops()
        # 启动每小时任务线程
        self.hourly_thread = threading.Thread(target=self.hourly_task, daemon=True)
        self.hourly_thread.start()
        
        # 启动每分钟任务线程
        self.minute_thread = threading.Thread(target=self.minute_task, daemon=True)
        self.minute_thread.start()
        
        print("✅ 调度器启动成功")
        print("   📡 每小时抓取空投信息")
        print("   🔔 每分钟检查提醒")
    
    def stop(self):
        """停止调度器"""
        if not self.running:
            print("⚠️ 调度器未在运行")
            return
        
        print("🛑 正在停止调度器...")
        self.running = False
        
        # 等待线程结束
        if hasattr(self, 'hourly_thread') and self.hourly_thread:
            self.hourly_thread.join(timeout=5)
        if hasattr(self, 'minute_thread') and self.minute_thread:
            self.minute_thread.join(timeout=5)
        
        print("✅ 调度器已停止")
    
    def status(self):
        """显示状态信息"""
        print(f"\n📊 调度器状态")
        print("=" * 50)
        print(f"运行状态: {'🟢 运行中' if self.running else '🔴 已停止'}")
        print(f"任务数量: {len(self.task_storage.tasks)}")
        
        # 计算活跃线程数
        active_threads = 0
        if hasattr(self, 'hourly_thread') and self.hourly_thread and self.hourly_thread.is_alive():
            active_threads += 1
        if hasattr(self, 'minute_thread') and self.minute_thread and self.minute_thread.is_alive():
            active_threads += 1
        print(f"活跃线程: {active_threads}")
        
        # 显示最近的任务
        if self.task_storage.tasks:
            print(f"\n📋 最近任务:")
            for i, (task_id, task) in enumerate(list(self.task_storage.tasks.items())[-5:], 1):
                airdrop = task.airdrop_info
                print(f"  {i}. {airdrop.name} ({airdrop.token}) - {airdrop.date} {airdrop.time}")
        
        # 显示需要提醒的任务
        need_reminder = self.task_storage.get_tasks_need_reminder()
        if need_reminder:
            print(f"\n🔔 待提醒任务:")
            for task_id, task, reminder_type in need_reminder:
                airdrop = task.airdrop_info
                print(f"  • {airdrop.name} ({airdrop.token}) - {reminder_type}")
        
        return {
            'running': self.running,
            'total_tasks': len(self.task_storage.tasks),
            'active_threads': active_threads
        }


def main():
    """主函数 - 演示功能"""
    import sys
    # 检查命令行参数
    test_mode = "--test" in sys.argv or "-t" in sys.argv
    if test_mode:
        print("🧪 启动测试模式（飞书通知已禁用）")
    scheduler = AirdropScheduler(test_mode=test_mode)
    try:
        print("🎯 空投调度器演示")
        print("=" * 50)
        # 显示当前状态
        scheduler.status()
        # 启动调度器
        scheduler.start()
        print("\n⌨️ 按 Ctrl+C 停止调度器")
        if test_mode:
            print("🧪 测试模式：不会发送飞书通知")
        
        # 保持运行
        while True:
            time.sleep(1)          
    except KeyboardInterrupt:
        print("\n\n🛑 接收到停止信号")
        scheduler.stop()
        print("👋 再见！")


if __name__ == "__main__":
    main()