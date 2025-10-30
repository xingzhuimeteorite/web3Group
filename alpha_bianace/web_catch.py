#!/usr/bin/env python3
"""
Alpha123.uk 空投信息抓取模块
功能：抓取空投名字、积分、数量、时间等信息
"""

import requests
import json
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class AirdropInfo:
    """空投信息数据类"""
    name: str           # 项目名称
    token: str          # 代币符号
    points: str         # 积分
    amount: str         # 数量
    time: str           # 时间
    date: str           # 日期
    status: str         # 状态
    type: str           # 类型
    
    def __str__(self):
        return f"{self.name}({self.token}) - 积分:{self.points} 数量:{self.amount} 时间:{self.date} {self.time}"


class WebCatch:
    """网页数据抓取器"""
    
    def __init__(self, base_url: str = "https://alpha123.uk"):
        self.base_url = base_url
        self.session = requests.Session()
        
        # 设置请求头，模拟浏览器
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': f'{base_url}/',
            'Connection': 'keep-alive',
        })
    
    def fetch_airdrops(self) -> List[AirdropInfo]:
        """
        抓取空投信息
        
        Returns:
            List[AirdropInfo]: 空投信息列表
        """
        try:
            # 请求API接口
            url = f"{self.base_url}/api/data?fresh=1"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # 检查是否有airdrops字段
            if 'airdrops' not in data:
                print(f"❌ API响应格式错误: 缺少airdrops字段")
                return []
            
            airdrops_data = data.get('airdrops', [])
            airdrops = []
            
            for item in airdrops_data:
                if not item:
                    continue
                    
                airdrop = AirdropInfo(
                    name=item.get('name', ''),
                    token=item.get('token', ''),
                    points=item.get('points', ''),
                    amount=item.get('amount', ''),
                    time=item.get('time', ''),
                    date=item.get('date', ''),
                    status=item.get('status', ''),
                    type=item.get('type', '')
                )
                airdrops.append(airdrop)
            
            return airdrops
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 网络请求失败: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            return []
        except Exception as e:
            print(f"❌ 抓取失败: {e}")
            return []
    
    def get_today_airdrops(self) -> List[AirdropInfo]:
        """
        获取今日空投
        
        Returns:
            List[AirdropInfo]: 今日空投列表
        """
        all_airdrops = self.fetch_airdrops()
        today = datetime.now().strftime('%Y-%m-%d')
        
        today_airdrops = [
            airdrop for airdrop in all_airdrops 
            if airdrop.date == today
        ]
        
        return today_airdrops
    
    def get_upcoming_airdrops(self, days: int = 7) -> List[AirdropInfo]:
        """
        获取即将到来的空投
        
        Args:
            days: 未来几天内的空投
            
        Returns:
            List[AirdropInfo]: 即将到来的空投列表
        """
        all_airdrops = self.fetch_airdrops()
        today = datetime.now()
        
        upcoming_airdrops = []
        for airdrop in all_airdrops:
            if not airdrop.date:
                continue
                
            try:
                airdrop_date = datetime.strptime(airdrop.date, '%Y-%m-%d')
                days_diff = (airdrop_date - today).days
                
                if 0 <= days_diff <= days:
                    upcoming_airdrops.append(airdrop)
            except ValueError:
                continue
        
        # 按日期排序
        upcoming_airdrops.sort(key=lambda x: x.date)
        return upcoming_airdrops
    
    def print_airdrops(self, airdrops: List[AirdropInfo], title: str = "空投信息"):
        """
        打印空投信息
        
        Args:
            airdrops: 空投列表
            title: 标题
        """
        print(f"\n🎁 {title}")
        print("=" * 60)
        
        if not airdrops:
            print("📭 暂无空投信息")
            return
        
        for i, airdrop in enumerate(airdrops, 1):
            print(f"{i:2d}. {airdrop.name} ({airdrop.token})")
            print(f"    📅 时间: {airdrop.date} {airdrop.time}")
            print(f"    🎯 积分: {airdrop.points or '未知'}")
            print(f"    💰 数量: {airdrop.amount or '未知'}")
            print(f"    📊 状态: {airdrop.status}")
            print(f"    🏷️  类型: {airdrop.type or '未知'}")
            print()


def main():
    """主函数 - 演示功能"""
    print("🚀 Alpha123.uk 空投信息抓取器")
    
    # 创建抓取器
    catcher = WebCatch()
    
    # 获取所有空投
    print("\n📡 正在抓取空投信息...")
    all_airdrops = catcher.fetch_airdrops()
    catcher.print_airdrops(all_airdrops, "所有空投信息")
    
    # 获取今日空投
    today_airdrops = catcher.get_today_airdrops()
    catcher.print_airdrops(today_airdrops, "今日空投")
    
    # 获取未来7天空投
    upcoming_airdrops = catcher.get_upcoming_airdrops(7)
    catcher.print_airdrops(upcoming_airdrops, "未来7天空投")
    
    print(f"\n📊 统计信息:")
    print(f"   总空投数量: {len(all_airdrops)}")
    print(f"   今日空投: {len(today_airdrops)}")
    print(f"   未来7天: {len(upcoming_airdrops)}")


if __name__ == "__main__":
    main()