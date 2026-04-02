import asyncio
import aiohttp
import os
import json
import re
import sys
import time
import random
import urllib3
import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# 1. 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 2. 路径配置
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.dirname(CURRENT_DIR) 
SOURCE_M3U = os.path.join(BASE_PATH, "hotels", "REBORN.m3u")

# 设定输出目录为 py/Hotel/
OUTPUT_DIR = os.path.join(BASE_PATH, "py", "Hotel")
OUTPUT_TXT = os.path.join(OUTPUT_DIR, "traffic_report.txt")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "traffic_summary.json")

# --- 性能配置 ---
TEST_DURATION = 15  # 每个 ID 测试 15 秒
SAMPLES_PER_IP = 3  # 每个 IP 随机抽 3 个 ID 压测
MAX_WORKERS = 10    # 并行线程数

def test_stream_traffic(name, url):
    """模拟播放并统计流量，计算 Mbps"""
    ip_port = urlparse(url).netloc
    start_time = time.time()
    total_bytes = 0
    speeds_mbps = []
    
    headers = {'User-Agent': 'Mozilla/5.0 (Viera; rv:34.0) Gecko/20100101 Firefox/34.0'}
    
    try:
        r = requests.get(url, timeout=5, headers=headers, verify=False)
        if r.status_code != 200: return None
        
        base_dir = url.rsplit('/', 1)[0]
        ts_lines = [line.strip() for line in r.text.split('\n') if line.strip() and not line.startswith('#')]
        if not ts_lines: return None

        while time.time() - start_time < TEST_DURATION:
            target_ts = ts_lines[-2:] if len(ts_lines) > 2 else ts_lines
            for ts_path in target_ts:
                if time.time() - start_time > TEST_DURATION: break
                ts_url = ts_path if ts_path.startswith('http') else f"{base_dir}/{ts_path}"
                
                ts_start = time.time()
                try:
                    ts_r = requests.get(ts_url, timeout=5, headers=headers, stream=True, verify=False)
                    chunk_bytes = 0
                    for chunk in ts_r.iter_content(chunk_size=128*1024):
                        if chunk:
                            chunk_bytes += len(chunk)
                            total_bytes += len(chunk)
                            if time.time() - start_time > TEST_DURATION: break
                    
                    ts_duration = time.time() - ts_start
                    if ts_duration > 0 and chunk_bytes > 10240:
                        mbps = (chunk_bytes * 8) / (ts_duration * 1024 * 1024)
                        speeds_mbps.append(mbps)
                except: continue
            time.sleep(1) 

    except Exception:
        return None

    test_time = time.time() - start_time
    if test_time > 0 and speeds_mbps:
        avg_speed = (total_bytes * 8) / (test_time * 1024 * 1024)
        max_speed = max(speeds_mbps)
        min_speed = min(speeds_mbps)
        stability = 1 - ((max_speed - min_speed) / avg_speed) if avg_speed > 0 else 0
        stability = max(0, min(1, stability))
        
        return {
            "name": name, "ip_port": ip_port,
            "avg_mbps": round(avg_speed, 2), "max_mbps": round(max_speed, 2),
            "stability": round(stability, 2)
        }
    return None

def save_reports(results, group_summary):
    """保存报告，确保目录存在"""
    # 自动创建 py/Hotel/ 目录
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(OUTPUT_TXT, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write(f"IPTV 酒店源流量测试报告 ({time.strftime('%Y-%m-%d %H:%M:%S')})\n")
        f.write("="*70 + "\n")
        f.write(f"{'服务器 (IP:Port)':<25} | {'频道名称':<20} | {'平均码率':<10} | {'稳定性'}\n")
        f.write("-" * 70 + "\n")
        
        sorted_res = sorted([r for r in results if r], key=lambda x: x['ip_port'])
        for res in sorted_res:
            f.write(f"{res['ip_port']:<25} | {res['name'][:18]:<20} | {res['avg_mbps']:<7}Mbps | {res['stability']*100:.0f}%\n")
        
        f.write("\n综合评估 (Summary):\n")
        for ip, summ in group_summary.items():
            f.write(f"{ip:<25} | 存活:{summ['alive_count']} | 均值:{summ['avg_mbps']}Mbps | 峰值:{summ['max_mbps']}Mbps\n")

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump({"summary": group_summary, "details": [r for r in results if r]}, f, ensure_ascii=False, indent=2)

def main():
    print(f"🚀 开始 IPTV 酒店源流量压测...")
    print(f"📂 输出目录: {OUTPUT_DIR}")
    
    if not os.path.exists(SOURCE_M3U):
        print(f"❌ 错误: 找不到源文件 {SOURCE_M3U}")
        return

    with open(SOURCE_M3U, 'r', encoding='utf-8') as f:
        content = f.read()

    groups = {}
    lines = content.split('\n')
    for i in range(len(lines)):
        if lines[i].startswith('#EXTINF') and i+1 < len(lines):
            url = lines[i+1].strip()
            if url.startswith('http'):
                ip_port = urlparse(url).netloc
                if not ip_port: continue
                if ip_port not in groups: groups[ip_port] = []
                name_match = re.search(r',(.+)$', lines[i])
                name = name_match.group(1).strip() if name_match else "Unknown"
                groups[ip_port].append((name, url))

    tasks = []
    for ip_port, urls in groups.items():
        samples = random.sample(urls, min(len(urls), SAMPLES_PER_IP))
        for s in samples:
            tasks.append(s)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_stream_traffic, n, u): (n, u) for n, u in tasks}
        for future in futures:
            try:
                res = future.result()
                if res: 
                    results.append(res)
                    print(f"✅ 完成: {res['ip_port']} - {res['avg_mbps']} Mbps")
            except Exception as e:
                print(f"⚠️ 测试出错: {e}")

    group_summary = {}
    for res in results:
        ip = res['ip_port']
        if ip not in group_summary:
            group_summary[ip] = {"alive_count": 0, "avg_mbps_list": [], "max_mbps": 0}
        s = group_summary[ip]
        s["alive_count"] += 1
        s["avg_mbps_list"].append(res['avg_mbps'])
        s["max_mbps"] = max(s["max_mbps"], res['max_mbps'])

    for ip, data in group_summary.items():
        if data["avg_mbps_list"]:
            data["avg_mbps"] = round(sum(data["avg_mbps_list"]) / len(data["avg_mbps_list"]), 2)
        else:
            data["avg_mbps"] = 0
        del data["avg_mbps_list"]

    save_reports(results, group_summary)
    print(f"\n✨ 测速任务结束！报告已保存至 {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
