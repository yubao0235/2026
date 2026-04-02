import os, re, socket, datetime

# --- 配置保持不变 ---
IP_DIR = "py/fofa/ip"
RTP_DIR = "py/fofa/rtp"
OUTPUT_TXT = "py/fofa/IPTV.txt"
OUTPUT_M3U = "py/fofa/IPTV.m3u"
M3U_DIR = "py/fofa/m3u_groups"
LOGO_BASE = "https://gcore.jsdelivr.net/gh/linyu345/tv/icon/"
CORE_SAT = ["湖南卫视", "东方卫视", "浙江卫视", "江苏卫视", "北京卫视", "湖北卫视", "深圳卫视"]

def verify_url(url):
    try:
        match = re.search(r'http://([^:/]+):?(\d+)?/', url)
        if not match: return False
        host, port = match.group(1), int(match.group(2)) if match.group(2) else 80
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            return s.connect_ex((host, port)) == 0
    except: return False

def clean_name(name):
    clean = re.sub(r'[\(\[\uff08].*?[\)\]\uff09]', '', name).upper().replace(" ", "").replace("-", "")
    # 保持 HD/4K 标记用于后续排序判断，但在最终显示前可根据需要处理
    m = re.search(r'CCTV(\d+)', clean)
    if m:
        num = m.group(1)
        if "5+" in clean: return "CCTV5+"
        return f"CCTV{num}"
    return clean

def get_sort_weight(name):
    """
    计算频道排序权重，分值越小越靠前
    1. 央视数字 (1-17): 100 + 数字
    2. 4K频道: 200
    3. 普通卫视 (CORE_SAT优先): 300
    4. 地方台 (地名开头): 400
    5. 其他频道: 500
    6. 央视非数字 (剧场等): 600
    """
    # 1. 央视数字类
    cctv_num = re.search(r'CCTV(\d+)', name)
    if cctv_num:
        return 100 + int(cctv_num.group(1))
    if name == "CCTV5+":
        return 118 # 排在17之后
    
    # 2. 4K 卫视
    if "4K" in name:
        return 200

    # 3. 卫视类
    if "卫视" in name:
        if any(s in name for s in CORE_SAT):
            return 300 # 核心卫视优先
        return 310 # 其他卫视

    # 4. 央视非数字剧场类 (判定规则：包含剧场或特定央视名称)
    if any(x in name for x in ["剧场", "兵器", "风云", "女性", "世界地理", "央视"]):
        return 600

    # 5. 地方台判定 (判断标准：以省份/地名开头且包含多个子频道)
    # 这里通过检查名字长度和常见地名简单判定
    provinces = ["山东", "江苏", "浙江", "广东", "湖南", "湖北", "河南", "河北", "安徽", "福建", "江西", "辽宁", "吉林", "黑龙江", "山西", "陕西", "甘肃", "青海", "四川", "贵州", "云南", "海南", "台湾", "北京", "天津", "上海", "重庆", "广西", "内蒙古", "西藏", "宁夏", "新疆"]
    if any(name.startswith(p) for p in provinces):
        return 400

    # 6. 其他
    return 500

def run_workflow():
    if not os.path.exists(IP_DIR): return
    if not os.path.exists(M3U_DIR): os.makedirs(M3U_DIR)
    
    # --- 组合屏蔽配置 ---
    # 敏感省份/城市
    SKIP_PROVINCES = ["上海", "江苏", "浙江", "广东", "四川", "南京", "湖北", "广州", "深圳"]
    # 敏感关键词 (涵盖电信、联通、移动)
    SKIP_KEYWORDS = ["电信", "联通", "移动", "酒店", "内网"]
    
    all_valid_data = []
    ip_files = sorted([f for f in os.listdir(IP_DIR) if f.endswith(".txt")])
    
    for f_name in ip_files:
        # 提取文件名主体
        isp_base = f_name.replace(".txt", "").replace("市", "")
        
        # --- 增强型过滤逻辑 ---
        should_skip = False
        # 第一层：检查是否属于敏感地区
        if any(prov in isp_base for prov in SKIP_PROVINCES):
            # 第二层：如果属于敏感地区，再检查是否命中屏蔽词（电信/联通/移动等）
            if any(key in isp_base for key in SKIP_KEYWORDS):
                should_skip = True
        
        if should_skip:
            print(f"🛡️  屏蔽敏感区域源: {isp_base} (已跳过)")
            continue
        # ------------------

        rtp_path = os.path.join(RTP_DIR, f_name)
        if not os.path.exists(rtp_path): continue

        with open(os.path.join(IP_DIR, f_name), 'r', encoding='utf-8') as f: 
            ips = f.read().splitlines()
        with open(rtp_path, 'r', encoding='utf-8') as f: 
            rtps = [l.strip() for l in f if "," in l]
        
        if not ips or not rtps: continue

        valid_count = 1
        for ip in ips:
            if not ip.strip(): continue
            test_url = f"http://{ip}/{'rtp' if 'rtp' in rtps[0] else 'udp'}/{rtps[0].split('://')[-1]}"
            print(f"📡 探测 [{isp_base}] {ip} ... ", end="", flush=True)
            
            if verify_url(test_url):
                print("✅")
                group_name = f"{isp_base}{valid_count}"
                for r_line in rtps:
                    name, r_url = r_line.split(',', 1)
                    c_name = clean_name(name)
                    all_valid_data.append({
                        "isp": isp_base, 
                        "group": group_name, 
                        "name": c_name, 
                        "url": f"http://{ip}/{'rtp' if 'rtp' in r_url else 'udp'}/{r_url.split('://')[-1]}",
                        "weight": get_sort_weight(c_name)
                    })
                valid_count += 1
            else: 
                print("❌")
    # ... (后续的排序和写入逻辑保持不变)

    if not all_valid_data: return
    
    # --- 核心排序逻辑改进 ---
    # 排序优先级：运营商 -> 组 -> 权重 -> 名字
    all_valid_data.sort(key=lambda x: (x['isp'], x['group'], x['weight'], x['name']))
    
    beijing_now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    # 写入文件逻辑
    with open(OUTPUT_TXT, 'w', encoding='utf-8') as f:
        f.write(f"更新时间: {beijing_now}\n")
        last_group = None
        for it in all_valid_data:
            if it['group'] != last_group:
                f.write(f"\n{it['group']},#genre#\n")
                last_group = it['group']
            f.write(f"{it['name']},{it['url']}\n")

    # 汇总 M3U
    with open(OUTPUT_M3U, 'w', encoding='utf-8') as f:
        f.write(f'#EXTM3U x-tvg-url="http://epg.51zmt.top:8000/e.xml" refresh="{beijing_now}"\n')
        for it in all_valid_data:
            logo = f"{LOGO_BASE}{it['name']}.png"
            f.write(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{it["group"]}",{it["name"]}\n{it["url"]}\n')

    print(f"\n✨ 处理完成，已按频道类型深度排版。")

if __name__ == "__main__":
    run_workflow()
