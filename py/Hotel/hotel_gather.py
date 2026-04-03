import os
import re
import asyncio
import httpx

# --- 配置区 ---
SOURCES = [
    "https://yede.us.ci/4d2e30e5.m3u",
    "https://yede.us.ci/edcab778.m3u",
    "https://yede.us.ci/33fc12a0.m3u",
    "https://yede.us.ci/3c1f32b7.m3u",
    "https://yede.us.ci/97d6e00d.m3u"
]

SAVE_DIR = "2026/Hotel"
# 免费的 IP 归属地 API (pypi.org 开源接口或 ip-api.com)
IP_API = "http://ip-api.com/json/{}?fields=status,regionName,city,query&lang=zh-CN"

async def get_location(client, ip):
    """查询 IP 归属地"""
    try:
        resp = await client.get(IP_API.format(ip), timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                region = data.get("regionName", "")
                city = data.get("city", "")
                # 如果城市和省份一样，只返回一个
                if region == city:
                    return region
                return f"{region}{city}"
    except:
        pass
    return "未知"

async def process_sources():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        # 1. 汇总所有 URL
        all_urls = set()
        for src in SOURCES:
            try:
                print(f"正在下载: {src}")
                r = await client.get(src)
                # 匹配 http 或 rtp 链接
                found = re.findall(r'(?:http|rtp)://[0-9\.]+(?::\d+)?', r.text)
                all_urls.update(found)
            except Exception as e:
                print(f"下载失败 {src}: {e}")

        print(f"共发现 {len(all_urls)} 个原始链接，开始处理归属地...")

        # 2. 提取 IP 并查询归属地
        tasks = []
        for url in all_urls:
            # 提取 IP 和端口
            match = re.search(r'//([0-9\.]+):(\d+)', url)
            if match:
                ip, port = match.groups()
                tasks.append((ip, port, url))

        # 限制并发，防止被 IP API 封禁
        for i in range(0, len(tasks), 10):
            batch = tasks[i:i+10]
            for ip, port, url in batch:
                loc = await get_location(client, ip)
                # 过滤掉非中文字符（可选，处理一些奇怪的 API 返回）
                loc = re.sub(r'[^\u4e00-\u9fa5]+', '', loc)
                if not loc: loc = "未知"
                
                filename = f"{loc}_{ip}_{port}.m3u"
                filepath = os.path.join(SAVE_DIR, filename)
                
                # 生成单文件内容
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    f.write(f"#EXTINF:-1,{loc}_{ip}\n")
                    f.write(f"{url}\n")
            
            print(f"已处理 {min(i+10, len(tasks))}/{len(tasks)}")
            await asyncio.sleep(1) # 礼貌延迟

if __name__ == "__main__":
    asyncio.run(process_sources())
