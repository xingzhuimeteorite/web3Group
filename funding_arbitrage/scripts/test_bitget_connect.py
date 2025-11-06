#!/usr/bin/env python3
"""
只读观察者（Bitget, ccxt）：
- 从本目录下的 config/config.json 读取配置
- 连接 Bitget（不下单），采样永续资金费并折算为日化
- 打印现货/永续余额摘要与开仓信号（基于阈值）
- 在连接失败时，提供详细的网络连通性诊断报告

运行：
  pip install ccxt requests
  python script/test_bitget_connect.py
"""

import json
from pathlib import Path
import sys
import os
import traceback
import requests
import time
import socket
from typing import Dict, Any

# 允许从父目录导入 config_loader
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_loader import load_config

try:
    import ccxt
except ImportError:
    print("[ERROR] 需要安装 ccxt：pip install ccxt")
    sys.exit(1)


# ==============================================================================
# Section 1: Network Connectivity Diagnostics
# ==============================================================================

def run_http_test(
    name: str, url: str, proxies: dict | None, timeout: float = 5.0
) -> dict:
    """执行单次 HTTP 请求测试，支持 SSL 错误时自动重试（不验证证书）。"""
    start = time.perf_counter()
    try:
        r = requests.get(url, timeout=timeout, proxies=proxies)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "name": name, "ok": 200 <= r.status_code < 400, "status": r.status_code,
            "elapsed_ms": elapsed_ms, "error": None, "alt_status": None,
        }
    except requests.exceptions.SSLError as e:
        # 尝试关闭证书校验
        alt_start = time.perf_counter()
        try:
            r2 = requests.get(url, timeout=timeout, verify=False, proxies=proxies)
            alt_elapsed_ms = int((time.perf_counter() - alt_start) * 1000)
            return {
                "name": name, "ok": False, "status": None, "elapsed_ms": None,
                "error": f"SSL: {e}", "alt_status": r2.status_code,
                "alt_ok": 200 <= r2.status_code < 400, "alt_elapsed_ms": alt_elapsed_ms,
            }
        except Exception as e2:
            return {
                "name": name, "ok": False, "status": None, "elapsed_ms": None,
                "error": f"SSL: {e}; alt_error: {e2}", "alt_status": None,
            }
    except Exception as e:
        return {
            "name": name, "ok": False, "status": None, "elapsed_ms": None,
            "error": str(e), "alt_status": None,
        }


def run_connectivity_suite(proxies: dict | None) -> tuple[dict, dict, dict, list[dict]]:
    """执行 DNS、TCP 和 HTTP 的全套连接测试。"""
    host = "api.bitget.com"
    # DNS
    try:
        infos = socket.getaddrinfo(host, 443)
        addrs = sorted({info[4][0] for info in infos})
        dns = {"ok": len(addrs) > 0, "addrs": addrs, "error": None}
    except Exception as e:
        dns = {"ok": False, "addrs": [], "error": str(e)}
    # TCP connect
    try:
        t0 = time.perf_counter()
        s = socket.create_connection((host, 443), timeout=3.0)
        s.close()
        tcp = {"ok": True, "elapsed_ms": int((time.perf_counter() - t0) * 1000), "error": None}
    except Exception as e:
        tcp = {"ok": False, "elapsed_ms": None, "error": str(e)}

    # HTTP endpoints
    http_tests = [
        ("spot coins", "https://api.bitget.com/api/v2/spot/public/coins"),
        ("mix current funding", "https://api.bitget.com/api/mix/v1/market/current-funding-rate?symbol=BTCUSDT_UMCBL"),
        ("mix funding history", "https://api.bitget.com/api/mix/v1/market/history-fundRate?symbol=BTCUSDT_UMCBL&pageSize=1"),
    ]
    http_results = [run_http_test(name, url, proxies) for name, url in http_tests]

    return proxies, dns, tcp, http_results


# ==============================================================================
# Section 2: Exchange & Data Fetching
# ==============================================================================

def make_exchange(
    perp_cfg: dict, proxies: dict | None = None, timeout_ms: int = 10000
) -> ccxt.Exchange:
    """根据配置创建并初始化 ccxt Exchange 实例。"""
    opts = perp_cfg.get("options", {})
    exchange = ccxt.bitget(
        {
            "apiKey": perp_cfg.get("apiKey", ""),
            "secret": perp_cfg.get("secret", ""),
            "password": perp_cfg.get("password", ""),
            "options": {
                "defaultType": opts.get("defaultType", "swap"),
                "defaultSubType": opts.get("defaultSubType", "USDT"),
                "fetchCurrencies": False,
            },
            "enableRateLimit": True,
            "timeout": timeout_ms,
        }
    )
    if proxies and (proxies.get("http") or proxies.get("https")):
        exchange.proxies = {k: v for k, v in proxies.items() if v}
    return exchange


def funding_rate_daily(
    exchange: ccxt.Exchange, symbol: str, thresholds: dict, interval_hours_default: int = 8
) -> tuple[dict | None, dict]:
    """获取资金费率并计算日化值。优先实时费率，失败则回退到历史记录。"""
    fr, hist, rate, interval_hours = None, None, None, interval_hours_default
    try:
        fr = exchange.fetch_funding_rate(symbol)
        rate, interval_hours = fr.get("fundingRate"), fr.get("fundingInterval", interval_hours_default)
    except Exception:
        try:
            hist = exchange.fetch_funding_history(symbol, limit=1)
            if hist: rate = hist[0].get("fundingRate")
        except Exception: pass

    if rate is None:
        return None, {"fr": fr, "hist_used": bool(hist)}

    try: interval_hours = float(interval_hours)
    except (ValueError, TypeError): interval_hours = interval_hours_default

    daily = rate * (24.0 / interval_hours)
    signal = daily >= float(thresholds.get("dailyFundingMin", 0.0))
    return {"rate": rate, "interval_hours": interval_hours, "daily": daily, "signal": signal}, {"fr": fr, "hist_used": bool(hist)}


def fetch_funding_via_http(proxies: dict | None = None) -> tuple[dict | None, dict]:
    """直接用 HTTP 请求 Bitget mix 资金费端点，作为 ccxt 失败的回退。"""
    url = "https://api.bitget.com/api/mix/v1/market/current-funding-rate?symbol=BTCUSDT_UMCBL"
    data, rate = None, None
    try:
        r = requests.get(url, timeout=5, proxies=proxies)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.SSLError:
        try:
            r = requests.get(url, timeout=5, verify=False, proxies=proxies)
            r.raise_for_status()
            data = r.json()
        except Exception as e: return None, {"error": str(e)}
    except Exception as e: return None, {"error": str(e)}

    try:
        if isinstance(data, dict) and data.get("data"):
            rate = float(data["data"]["fundingRate"])
    except (ValueError, TypeError, KeyError): rate = None

    if rate is None: return None, {"raw": data}
    daily = rate * (24.0 / 8.0)
    return {"rate": rate, "interval_hours": 8.0, "daily": daily, "signal": None}, {"raw": data}


def coin_bal(bal: dict | None, coin: str) -> dict:
    """从 ccxt 的余额结构中安全地提取指定币种的余额。"""
    if not isinstance(bal, dict): return {"free": None, "used": None, "total": None}
    sub = bal.get(coin, {}) if isinstance(bal.get(coin, {}), dict) else {}
    free, used, total = sub.get("free"), sub.get("used"), sub.get("total")
    free = bal.get("free", {}).get(coin) if free is None and isinstance(bal.get("free"), dict) else free
    used = bal.get("used", {}).get(coin) if used is None and isinstance(bal.get("used"), dict) else used
    total = bal.get("total", {}).get(coin) if total is None and isinstance(bal.get("total"), dict) else total
    return {"free": free, "used": used, "total": total}


# ==============================================================================
# Section 3: Reporting
# ==============================================================================

def print_connectivity_report(proxies: dict, dns: dict, tcp: dict, http_results: list[dict]):
    """打印格式化的网络诊断报告。"""
    def badge(ok: bool): return "[PASS]" if ok else "[FAIL]"
    print("\n=== Network Diagnostics ===")
    print(f"Proxies: HTTP={proxies.get('http') or '-'} HTTPS={proxies.get('https') or '-'}")
    print(f"DNS: {badge(dns['ok'])} addrs={dns.get('addrs')} error={dns.get('error')}")
    print(f"TCP: {badge(tcp['ok'])} elapsed_ms={tcp.get('elapsed_ms')} error={tcp.get('error')}")
    print("HTTP endpoints:")
    for item in http_results:
        line = f"- {item['name']:<22}: {badge(item['ok'])} status={item.get('status') or 'N/A'} elapsed_ms={item.get('elapsed_ms') or 'N/A'}"
        if item.get('error'): line += f" error={item['error']}"
        if item.get('alt_status') is not None: line += f"; alt_verify_false: status={item['alt_status']}"
        print(line)
    print("建议:\n- 若诊断全 FAIL，检查本机网络、防火墙或代理配置。\n- 若仅 SSL 错误，可能是证书问题，临时可忽略校验，但有风险。")


def print_summary(spot_ok: bool, perp_ok: bool, fr_daily: dict | None):
    """打印最终的摘要信息。"""
    def badge(ok: bool): return "PASS" if ok else "FAIL"
    funding_ok = fr_daily is not None
    daily_str = f"{fr_daily['daily']:.6f}" if funding_ok else "-"
    print("\n=== Summary ===")
    print(f"现货连接: {badge(spot_ok)}")
    print(f"合约连接: {badge(perp_ok)}")
    print(f"资金费采样: {badge(funding_ok)} (Daily={daily_str})")
    print("\n[NOTE] 观察者模式，不会下单。")


# ==============================================================================
# Section 4: Main Execution
# ==============================================================================

def main():
    """主执行函数"""
    cfg, path = load_config()
    print(f"[INFO] Loaded config: {path}")

    # --- 配置解析 ---
    perp_cfg = cfg.get("exchanges", {}).get("perp", {})
    markets = cfg.get("markets", {})
    symbols = cfg.get("symbols", [])
    spot_symbol = markets.get("spot") or (symbols[0] if symbols else "BTC/USDT")
    perp_symbol = markets.get("perp") or f"{spot_symbol}:USDT"
    thresholds = cfg.get("thresholds", {})
    position = cfg.get("position", {})
    costs = cfg.get("costs", {})
    net_cfg = cfg.get("network", {})
    cfg_proxies = net_cfg.get("proxies") or cfg.get("proxies") or {}
    timeout_sec = net_cfg.get("timeout_sec", 10)
    try: timeout_ms = int(float(timeout_sec) * 1000)
    except (ValueError, TypeError): timeout_ms = 10000

    # --- 交易所初始化 ---
    ex = make_exchange(perp_cfg, cfg_proxies, timeout_ms)
    try:
        ex.load_markets({"type": "swap"})
    except Exception as e:
        print(f"[WARN] load_markets 失败：{e}，尝试仅用 swap 接口继续")
        ex.options["defaultType"] = "swap"

    # --- 连通性与余额检查 ---
    print("\n=== Connectivity & Balances ===")
    try:
        ex.options["defaultType"] = "swap"
        perp_bal = ex.fetch_balance()
        perp_conn_ok = True
        print(f"Perp Balances: {list(perp_bal.keys())[:5]}...")
    except Exception as e:
        perp_bal, perp_conn_ok = None, False
        print(f"Perp Balances: [FAIL] {e}")

    try:
        ex.options["defaultType"] = "spot"
        spot_bal = ex.fetch_balance()
        spot_conn_ok = True
        print(f"Spot Balances: {list(spot_bal.keys())[:5]}...")
    except Exception as e:
        spot_bal, spot_conn_ok = None, False
        print(f"Spot Balances: [FAIL] {e}")

    ex.options["defaultType"] = "swap"  # 还原

    base = spot_symbol.split('/')[0]
    usdt_perp, usdt_spot, base_spot = coin_bal(perp_bal, "USDT"), coin_bal(spot_bal, "USDT"), coin_bal(spot_bal, base)
    print(f"  - Perp USDT: free={usdt_perp['free']} total={usdt_perp['total']}")
    print(f"  - Spot USDT: free={usdt_spot['free']} total={usdt_spot['total']}")
    print(f"  - Spot {base}: free={base_spot['free']} total={base_spot['total']}")

    # --- 资金费率获取 ---
    print("\n=== Funding Rate ===")
    print(f"Symbol: {perp_symbol}")
    fr_daily, _ = funding_rate_daily(ex, perp_symbol, thresholds)

    if fr_daily:
        print(f"  - FundingRate: {fr_daily['rate']:.6f}")
        print(f"  - DailyFunding: {fr_daily['daily']:.6f}")
        print(f"  - Signal(daily >= {thresholds.get('dailyFundingMin')}): {fr_daily['signal']}")
    else:
        print("  - Funding fetch via ccxt failed. Trying HTTP fallback...")
        http_fr, _ = fetch_funding_via_http(cfg_proxies)
        if http_fr:
            fr_daily = http_fr  # 使用 HTTP 回退的结果
            print(f"  - [HTTP Fallback] Success: DailyFunding={http_fr['daily']:.6f}")
        else:
            print("  - [HTTP Fallback] Failed. Running network diagnostics...")
            proxies, dns, tcp, http_results = run_connectivity_suite(cfg_proxies)
            print_connectivity_report(proxies, dns, tcp, http_results)

    # --- 打印仓位与成本配置 ---
    print("\n=== Position & Costs (Config) ===")
    print(f"NotionalUSD: {position.get('notional_usd')}, Leverage: {position.get('futures_margin_leverage')}")
    print(f"TakerBps: {costs.get('taker_bps')}, MakerBps: {costs.get('maker_bps')}, SlippageBps: {costs.get('slippage_bps')}")

    # --- 最终汇总 ---
    print_summary(spot_conn_ok, perp_conn_ok, fr_daily)


if __name__ == "__main__":
    main()
