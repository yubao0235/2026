import asyncio
import aiohttp
import re
import os
import base64
import random  # 注入随机库

# --- 配置区 ---
COOKIE = os.getenv("FOFA_COOKIE", "") 

# 定义你想要扫描的端口列表
PORTS = ["9901", "7777", "9999", "808", "9902"] 

# 默认的 JSON 路径（大部分酒店通用）
TARGET_PATH = "/iptv/live/1000.json?key=txiptv"
OUTPUT_DIR = "Hotel"

async def fetch_fofa_ips(session):
    # 同样建议清洗一次 Cookie 确保没有换行符
    clean_cookie = COOKIE.replace('\n', '').replace('\r', '').strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Cookie": clean_cookie,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    
    all_found_ips = []

    for index, port in enumerate(PORTS):
        # --- 核心改进：非第一个请求时，随机等待 5-12 秒 ---
        if index > 0:
            wait_time = random.uniform(5, 12) 
            print(f"⏳ 为规避 429 限制，随机等待 {wait_time:.1f} 秒...", flush=True)
            await asyncio.sleep(wait_time)
        
        query = f'port="{port}" && "/iptv/live"'
        qbase64 = base64.b64encode(query.encode()).decode()
        
        url = f"https://fofa.info/result?qbase64={qbase64}&filter_type=last_month&size=100&sort_hash=lastupdatetime%3Adesc"
        
        print(f"📡 正在抓取端口 [{port}] 的节点...", flush=True)
        try:
            async with session.get(url, headers=headers, timeout=20) as resp:
                # 如果依然触发 429，则进入“强力冷冻”模式
                if resp.status == 429:
                    print(f"⚠️ 端口 {port} 触发 429，该端口将跳过，并在下个端口前额外休息 20 秒...")
                    await asyncio.sleep(20)
                    continue
                
                if resp.status != 200:
                    print(f"⚠️ 端口 {port} 访问受限 (状态码: {resp.status})")
                    continue
                
                text = await resp.text()
                ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', text)
                valid_ips = list(set([ip for ip in ips if not ip.startswith(("127.", "0.", "10."))]))
                
                for ip in valid_ips:
                    all_found_ips.append((ip, port))
                print(f"✅ 端口 [{port}] 提取到 {len(valid_ips)} 个潜在 IP")
        except Exception as e:
            print(f"❌ 抓取端口 {port} 时发生异常: {e}")
            
    return list(set(all_found_ips))

async def get_location(session, ip):
    try:
        await asyncio.sleep(1) # 稍微慢一点，防止被 IP-API 封禁
        async with session.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=5) as resp:
            data = await resp.json()
            if data.get('status') == 'success':
                r = data.get('regionName', '').replace("省","").replace("市","")
                c = data.get('city', '').replace("省","").replace("市","")
                return r if r == c else f"{r}{c}"
    except: pass
    return "未知"

async def process_node(session, ip_info, semaphore):
    ip, port = ip_info
    check_url = f"http://{ip}:{port}{TARGET_PATH}"
    async with semaphore:
        try:
            async with session.get(check_url, timeout=8) as resp:
                if resp.status == 200:
                    json_data = await resp.json()
                    channels = json_data.get('data', [])
                    if channels:
                        loc = await get_location(session, ip)
                        filename = f"{loc}_{ip}_{port}.m3u"
                        filepath = os.path.join(OUTPUT_DIR, filename)
                        
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write("#EXTM3U\n")
                            for ch in channels:
                                name = ch.get('name')
                                m_url = ch.get('url', '')
                                if m_url and not m_url.startswith("http"):
                                    m_url = f"http://{ip}:{port}{m_url}"
                                f.write(f"#EXTINF:-1,{name}\n{m_url}\n")
                        print(f"⭐ 发现有效节点: {filename}")
                        return True
        except: pass
    return False

async def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    async with aiohttp.ClientSession() as session:
        ip_list = await fetch_fofa_ips(session)
        if not ip_list:
            print("⚠️ 未抓取到任何有效 IP。")
            return

        print(f"🚀 开始并发检测 {len(ip_list)} 个节点...")
        semaphore = asyncio.Semaphore(50) 
        tasks = [process_node(session, item, semaphore) for item in ip_list]
        results = await asyncio.gather(*tasks)
        
        # --- 自动生成汇总文件 ---
        all_content = ["#EXTM3U"]
        for file in os.listdir(OUTPUT_DIR):
            if file.endswith(".m3u") and file != "Hotel_All.m3u":
                with open(os.path.join(OUTPUT_DIR, file), "r", encoding="utf-8") as f:
                    all_content.extend(f.readlines()[1:])
        
        with open(os.path.join(OUTPUT_DIR, "Hotel_All.m3u"), "w", encoding="utf-8") as f:
            f.write("\n".join(all_content))
            
        print(f"✨ 处理完成。共发现 {sum(1 for r in results if r)} 个存活源。")
        print(f"📦 汇总文件已生成: {OUTPUT_DIR}/Hotel_All.m3u")

if __name__ == "__main__":
    asyncio.run(main())
