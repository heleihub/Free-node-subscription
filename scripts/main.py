import os
import re
import sys
import json
import time
import gzip
import base64
import shutil
import socket
import urllib.request
import urllib.parse
import subprocess
import requests
import yaml
import maxminddb
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------- 1. 你指定的最新高权重源池 -----------------
SOURCE_URLS = [
    # 用户指定的优质源池
    "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/all.txt",
    "https://raw.githubusercontent.com/10ium/HiN-VPN/main/subscription/base64/mix",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/protocols/hysteria",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/security/tls",
    "https://shatakvpn.github.io/ConfigForge-V2Ray",
    "https://10ium.github.io/free-sub-link",
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/v2ray-base64.txt",
    
    # 辅助兜底大池
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreGFW/master/subs/base64.txt",
]

SCRAPE_WEBSITES = [
    "https://outlinekeys.com/protocols/vless/",
    "https://shadowmere.xyz/",
    "https://shadowmere.xyz/api/vless",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RESIDENTIAL_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")
os.makedirs(COUNTRY_DIR, exist_ok=True)
os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)

# 知名民用家宽网络运营商关键字（强家宽白名单）
RESIDENTIAL_KEYWORDS = [
    "telecom", "broadband", "consumer", "cable", "dsl", "hinet", 
    "chunghwa", "comcast", "charter", "spectrum", "verizon", "att",
    "bell", "rogers", "shaw", "vodafone", "orange", "deutsche telekom",
    "virgin media", "kddi", "softbank", "ntt", "so-net", "kt", "sk broadband",
    "lguplus", "home", "residential", "starhub", "singtel"
]

COUNTRY_META = {
    "HK": ("🇭🇰", "香港 (Hong Kong)"),
    "TW": ("🇹🇼", "台湾 (Taiwan)"),
    "JP": ("🇯🇵", "日本 (Japan)"),
    "SG": ("🇸🇬", "新加坡 (Singapore)"),
    "US": ("🇺🇸", "美国 (United States)"),
    "KR": ("🇰🇷", "韩国 (South Korea)"),
    "DE": ("🇩🇪", "德国 (Germany)"),
    "GB": ("🇬🇧", "英国 (United Kingdom)"),
    "CA": ("🇨🇦", "加拿大 (Canada)"),
    "FR": ("🇫🇷", "法国 (France)"),
    "NL": ("🇳🇱", "荷兰 (Netherlands)"),
    "RU": ("🇷🇺", "俄罗斯 (Russia)"),
    "OTHER": ("🌐", "其他地区 (Other)"),
}

def safe_download(url, dest_path):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def setup_environment():
    print("[*] 正在准备依赖环境与数据库...")
    if not os.path.exists("Country.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb", "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb", "ASN.mmdb")
    
    if not os.path.exists("mihomo"):
        print("[*] 正在下载 mihomo 测活内核...")
        safe_download("https://github.com/MetaCubeX/mihomo/releases/download/v1.18.9/mihomo-linux-amd64-v1.18.9.gz", "mihomo.gz")
        with gzip.open("mihomo.gz", "rb") as f_in, open("mihomo", "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.chmod("mihomo", 0o755)
        if os.path.exists("mihomo.gz"):
            os.remove("mihomo.gz")

def extract_nodes_from_text(text):
    results = set()
    if not text:
        return results

    # 递归解码 Base64
    for _ in range(2):
        try:
            padded = text.strip() + '=' * (-len(text.strip()) % 4)
            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
            if any(p in decoded for p in ["vmess://", "vless://", "ss://", "trojan://"]):
                text += "\n" + decoded
        except Exception:
            pass

    pattern = r'((?:vmess|vless|ss|trojan)://[^\s"\'<>]+)'
    for m in re.findall(pattern, text):
        clean = m.strip().rstrip(".,;\"')")
        results.add(clean)
    return results

def fetch_raw_nodes():
    nodes = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    print("[*] 正在抓取全部节点源池...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            extracted = extract_nodes_from_text(resp.text)
            nodes.update(extracted)
            print(f"[+] 成功抓取: {url} -> 获得 {len(extracted)} 个节点")
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")

    for site in SCRAPE_WEBSITES:
        try:
            resp = requests.get(site, headers=headers, timeout=20)
            if resp.status_code == 200:
                extracted = extract_nodes_from_text(resp.text)
                nodes.update(extracted)
                print(f"[+] 网页端提取成功: {site} -> 获得 {len(extracted)} 个节点")
        except Exception as e:
            print(f"[!] 网页提取失败 {site}: {e}")
            
    print(f"[*] 节点池初始去重总量: {len(nodes)} 个")
    return list(nodes)

def convert_node_to_clash(node_str, index):
    name = f"node_{index}"
    try:
        if node_str.startswith("vmess://"):
            b64 = node_str[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            server = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            uuid = str(data.get("id", "")).strip()
            if not server or port <= 0 or port > 65535 or not uuid:
                return None

            proxy = {
                "name": name,
                "type": "vmess",
                "server": server,
                "port": port,
                "uuid": uuid,
                "alterId": int(data.get("aid", 0)),
                "cipher": "auto",
                "udp": True,
                "tls": True if data.get("tls") in ["tls", "1"] else False,
                "skip-cert-verify": True
            }
            if data.get("net") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = {
                    "path": data.get("path", "/"),
                    "headers": {"Host": str(data.get("host", server)).strip()}
                }
            return proxy

        elif node_str.startswith("vless://"):
            m = re.search(r"vless://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                uuid, server, port_s, query = m.groups()
                server = server.strip()
                port = int(port_s)
                uuid = uuid.strip()
                if not server or port <= 0 or port > 65535 or not uuid:
                    return None

                params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
                is_tls = params.get("security") in ["tls", "reality"]
                proxy = {
                    "name": name,
                    "type": "vless",
                    "server": server,
                    "port": port,
                    "uuid": uuid,
                    "udp": True,
                    "tls": is_tls,
                    "skip-cert-verify": True
                }
                if params.get("security") == "reality":
                    pbk = params.get("pbk", "").strip()
                    if not pbk:
                        return None
                    proxy["reality-opts"] = {
                        "public-key": pbk,
                        "short-id": params.get("sid", "").strip()
                    }
                    proxy["servername"] = params.get("sni", server).strip()
                    proxy["client-fingerprint"] = params.get("fp", "chrome")
                if params.get("type") == "ws":
                    proxy["network"] = "ws"
                    proxy["ws-opts"] = {
                        "path": urllib.parse.unquote(params.get("path", "/")),
                        "headers": {"Host": params.get("host", server).strip()}
                    }
                return proxy

        elif node_str.startswith("trojan://"):
            m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                password, server, port_s, query = m.groups()
                server = server.strip()
                port = int(port_s)
                password = password.strip()
                if not server or port <= 0 or port > 65535 or not password:
                    return None

                params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
                proxy = {
                    "name": name,
                    "type": "trojan",
                    "server": server,
                    "port": port,
                    "password": password,
                    "udp": True,
                    "sni": params.get("sni", server).strip(),
                    "skip-cert-verify": True
                }
                return proxy
    except Exception:
        pass
    return None

def run_real_delay_test(clash_proxies, port=19090, secret="secret123"):
    """使用 mihomo 内核通过真实代理链路访问 Google 204 进行严格连通性测试"""
    if not clash_proxies:
        return {}

    print(f"[*] 启动 mihomo 内核进行真连接测活，测试规模: {len(clash_proxies)} 个节点...")
    config = {
        "mixed-port": 17890,
        "mode": "rule",
        "log-level": "silent",
        "external-controller": f"127.0.0.1:{port}",
        "secret": secret,
        "proxies": clash_proxies
    }
    with open("temp_clash.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    proc = subprocess.Popen(["./mihomo", "-d", ".", "-f", "temp_clash.yaml"])
    time.sleep(4)

    alive_nodes = {}
    test_url = "http://www.google.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            r = requests.get(url, params={"url": test_url, "timeout": 3500}, headers=headers, timeout=5)
            if r.status_code == 200:
                delay = r.json().get("delay", 0)
                if delay > 0:
                    return name, delay
        except Exception:
            pass
        return None

    try:
        with ThreadPoolExecutor(max_workers=60) as executor:
            results = executor.map(check_proxy, clash_proxies)
            for res in results:
                if res:
                    alive_nodes[res[0]] = res[1]
    finally:
        proc.kill()
        proc.wait()
        if os.path.exists("temp_clash.yaml"):
            os.remove("temp_clash.yaml")

    print(f"[+] 严格真连接检测完毕，绝对可用节点数量: {len(alive_nodes)}")
    return alive_nodes

def classify_and_filter(alive_proxies, node_map):
    """通过 ASN 与组织识别严格辨别国家及民用住宅家宽 (Residential)"""
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    def resolve_and_tag(item):
        name, delay = item
        original_link, p_obj = node_map[name]
        server = p_obj["server"]
        try:
            ip = socket.gethostbyname(server)
        except Exception:
            return None

        country_code = "OTHER"
        try:
            c = country_reader.get(ip)
            if c and "country" in c:
                country_code = c["country"]["iso_code"]
        except Exception:
            pass

        # 严格家宽判定：必须非机房 ASN，并且组织名符合民用宽带/电信商特征
        is_residential = False
        try:
            a = asn_reader.get(ip)
            if a:
                asn = a.get("autonomous_system_number", 0)
                org = str(a.get("autonomous_system_organization", "")).lower()
                
                # 排除机房，同时满足民用电信特征
                if asn not in DATACENTER_ASNS:
                    if any(k in org for k in RESIDENTIAL_KEYWORDS):
                        is_residential = True
        except Exception:
            pass

        return {
            "link": original_link,
            "clash_proxy": p_obj,
            "country": country_code,
            "is_residential": is_residential,
            "delay": delay
        }

    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(resolve_and_tag, item) for item in alive_proxies.items()]
        for f in as_completed(futures):
            res = f.result()
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()
    return verified

def export_clash_yaml(clash_proxies, filepath):
    """导出标准的 Clash 完整订阅文件"""
    names = [p["name"] for p in clash_proxies]
    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": clash_proxies,
        "proxy-groups": [
            {
                "name": "PROXIES",
                "type": "select",
                "proxies": ["AUTO"] + names
            },
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "http://www.google.com/generate_204",
                "interval": 300,
                "proxies": names
            }
        ],
        "rules": [
            "MATCH,PROXIES"
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def export_singbox_json(verified_nodes, filepath):
    """导出标准的 sing-box 完整订阅文件"""
    outbounds = [
        {"type": "selector", "tag": "select", "outbounds": ["auto"] + [f"node_{i}" for i in range(len(verified_nodes))]},
        {"type": "urltest", "tag": "auto", "outbounds": [f"node_{i}" for i in range(len(verified_nodes))], "url": "http://www.google.com/generate_204"}
    ]
    # 附带直连和拦截
    outbounds.append({"type": "direct", "tag": "direct"})
    outbounds.append({"type": "block", "tag": "block"})
    
    config = {
        "version": 1,
        "outbounds": outbounds
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def export_subscriptions(verified_nodes):
    """生成 V2Ray 通用 Base64、Clash YAML、sing-box JSON 多格式文件"""
    all_links = [n["link"] for n in verified_nodes]
    all_clash_proxies = [n["clash_proxy"] for n in verified_nodes]
    
    residential_nodes = [n for n in verified_nodes if n["is_residential"]]
    residential_links = [n["link"] for n in residential_nodes]
    residential_clash = [n["clash_proxy"] for n in residential_nodes]

    # 1. 全部节点导出 (V2Ray Base64, Clash, sing-box)
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())
    export_clash_yaml(all_clash_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    export_singbox_json(verified_nodes, os.path.join(OUTPUT_DIR, "singbox.json"))

    # 2. 全部家宽节点导出
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(residential_links).encode()).decode())
    if residential_clash:
        export_clash_yaml(residential_clash, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
        export_singbox_json(residential_nodes, os.path.join(OUTPUT_DIR, "residential-singbox.json"))

    # 3. 按国家分类导出全部节点
    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n)

    for cc, nodes_list in by_cc.items():
        links = [n["link"] for n in nodes_list]
        proxies = [n["clash_proxy"] for n in nodes_list]
        with open(os.path.join(COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        export_clash_yaml(proxies, os.path.join(COUNTRY_DIR, f"clash-{cc}.yaml"))

    # 4. 按国家分类导出家宽节点
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, nodes_list in res_by_cc.items():
        links = [n["link"] for n in nodes_list]
        proxies = [n["clash_proxy"] for n in nodes_list]
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        export_clash_yaml(proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))

    print(f"[*] 导出成功！全部可用节点: {len(all_links)} | 家宽节点: {len(residential_links)} | 覆盖国家: {len(by_cc)}")
    return by_cc, res_by_cc, len(all_links), len(residential_links)

def update_readme(by_cc, res_by_cc, total_count, res_count):
    """自动生成并刷新 README.md 页面数据表格与直链"""
    repo = os.environ.get("GITHUB_REPOSITORY", "heleihub/free-node-subscription")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 构建家宽国家表格
    all_res_countries = sorted(res_by_cc.keys(), key=lambda c: len(res_by_cc[c]), reverse=True)
    res_table_rows = []
    for cc in all_res_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / 其他"))
        count = len(res_by_cc.get(cc, []))
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/clash-{cc}.yaml"
        res_table_rows.append(f"| {flag} {name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    res_table_str = "\n".join(res_table_rows) if res_table_rows else "| 暂无可用家宽节点 | 0 | - | - |"

    # 构建全量国家表格
    all_countries = sorted(by_cc.keys(), key=lambda c: len(by_cc[c]), reverse=True)
    country_table_rows = []
    for cc in all_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / 其他"))
        count = len(by_cc.get(cc, []))
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/clash-{cc}.yaml"
        country_table_rows.append(f"| {flag} {name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    country_table_str = "\n".join(country_table_rows) if country_table_rows else "| 暂无可用节点 | 0 | - | - |"

    readme_content = f"""# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 🕒 **最近更新时间**: `{now_utc}`  
> 🟢 **全部可用节点数量**: `{total_count}` 个  
> 🏠 **甄选家宽节点数量**: `{res_count}` 个  
> ⚡ **质量检测标准**: 所有节点由 `mihomo` 代理内核通过建立真实代理通道访问 `Google 204`，剔除延迟超时及假连通节点。

---

## 📌 全部节点总订阅链接 (推荐导入)

| 客户端 / 格式类型 | 节点总数 | 免翻 CDN 订阅直链 (复制到客户端直接使用) |
| :--- | :---: | :--- |
| 🚀 **Clash (YAML 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/clash.yaml` |
| ⚡ **V2Ray / 通用 Base64** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/v2ray.txt` |
| 📦 **sing-box (JSON 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/singbox.json` |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 严格过滤主流机房 IP，筛选出归属于民用电信运营商宽带（Hinet、Comcast、Spectrum 等）的纯净家宽节点。

| 家宽地区 | 可用节点数 | 通用订阅链接 (V2Ray/Shadowrocket) | Clash 专属订阅 |
| :--- | :---: | :--- | :--- |
{res_table_str}

---

## 🗺️ 按照国家分类节点订阅 (全部可用节点)

| 地区/国家 | 可用节点数 | 通用订阅链接 (V2Ray/Shadowrocket) | Clash 专属订阅 |
| :--- | :---: | :--- | :--- |
{country_table_str}

---

## 🛠️ 项目使用说明
1. **自动更新机制**：GitHub Actions 每 6 小时全自动运行并更新上方的节点数量与订阅内容。
2. **多客户端兼容**：
   - **Clash / Clash Verge / Flash / Mihomo Party**：直接复制上方表格中的 **Clash 订阅** 链接。
   - **v2rayN / v2rayNG / Shadowrocket (小火箭)**：直接复制 **V2Ray/通用** 链接。
   - **sing-box**：直接使用上方 `singbox.json` 直链。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("[+] README.md 页面数据统计与多格式直链已自动重新生成并写入！")

if __name__ == "__main__":
    setup_environment()
    raw_nodes = fetch_raw_nodes()

    clash_list = []
    node_map = {}
    for i, raw in enumerate(raw_nodes):
        c_obj = convert_node_to_clash(raw, i)
        if c_obj:
            clash_list.append(c_obj)
            node_map[c_obj["name"]] = (raw, c_obj)

    alive_dict = run_real_delay_test(clash_list)
    verified = classify_and_filter(alive_dict, node_map)
    by_cc, res_by_cc, total_cnt, res_cnt = export_subscriptions(verified)
    update_readme(by_cc, res_by_cc, total_cnt, res_cnt)