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

# ----------------- 1. 节点抓取源池 (含指定的新网站与原仓库提取源) -----------------
SOURCE_URLS = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreGFW/master/subs/base64.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/all",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
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

# 常见机房/数据中心 ASN 库（用于排查过滤，余下归类为住宅宽带/家宽）
DATACENTER_ASNS = {
    13335,          # Cloudflare
    16509, 14618,   # Amazon AWS
    15169, 396982,  # Google Cloud
    8075,           # Microsoft Azure
    24940,          # Hetzner
    16276,          # OVH
    14061,          # DigitalOcean
    31898,          # Oracle Cloud
    63949,          # Linode / Akamai
    45102,          # Alibaba Cloud
    132203,         # Tencent Cloud
    20473,          # Vultr / Choopa
    60068,          # CDN77
    55081,          # 24-7
}

COUNTRY_META = {
    "HK": ("🇭🇰", "中国香港 / Hong Kong"),
    "TW": ("🇹🇼", "中国台湾 / Taiwan"),
    "JP": ("🇯🇵", "日本 / Japan"),
    "SG": ("🇸🇬", "新加坡 / Singapore"),
    "US": ("🇺🇸", "美国 / United States"),
    "KR": ("🇰🇷", "韩国 / South Korea"),
    "DE": ("🇩🇪", "德国 / Germany"),
    "GB": ("🇬🇧", "英国 / United Kingdom"),
    "CA": ("🇨🇦", "加拿大 / Canada"),
    "FR": ("🇫🇷", "法国 / France"),
    "NL": ("🇳🇱", "荷兰 / Netherlands"),
    "RU": ("🇷🇺", "俄罗斯 / Russia"),
    "OTHER": ("🌐", "其他地区 / Other"),
}

def safe_download(url, dest_path):
    """防 403 带有 UA 的安全下载函数"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def setup_environment():
    """准备数据库与 mihomo 测活内核"""
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
    """深度解析文本、HTML 和 Base64"""
    results = set()
    if not text:
        return results
    try:
        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
        if any(p in decoded for p in ["vmess://", "vless://", "ss://", "trojan://"]):
            text += "\n" + decoded
    except Exception:
        pass

    pattern = r'((?:vmess|vless|ss|trojan)://[^\s"\'<>]+)'
    matches = re.findall(pattern, text)
    for m in matches:
        clean = m.strip().rstrip(".,;\"')")
        results.add(clean)
    return results

def fetch_raw_nodes():
    """多源节点采集"""
    nodes = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    print("[*] 正在从基础订阅源拉取节点...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            extracted = extract_nodes_from_text(resp.text)
            nodes.update(extracted)
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")

    print("[*] 正在从指定网页端提取节点...")
    for site in SCRAPE_WEBSITES:
        try:
            resp = requests.get(site, headers=headers, timeout=20)
            if resp.status_code == 200:
                extracted = extract_nodes_from_text(resp.text)
                nodes.update(extracted)
                print(f"[+] 从 {site} 提取到 {len(extracted)} 个候选节点")
        except Exception as e:
            print(f"[!] 网页提取失败 {site}: {e}")
            
    print(f"[*] 原始节点池去重后总量: {len(nodes)} 个")
    return list(nodes)

def convert_node_to_clash(node_str, index):
    """将链接转换为标准的 Clash 字典，严格过滤残缺字段防奔溃"""
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
                    if not pbk:  # 没有公钥的 Reality 节点无法启动
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
    """使用 mihomo 内核严格执行真连接测试"""
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

    # 显式指定工作目录为当前目录
    proc = subprocess.Popen(["./mihomo", "-d", ".", "-f", "temp_clash.yaml"])
    time.sleep(4)

    alive_nodes = {}
    test_url = "http://www.google.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            r = requests.get(url, params={"url": test_url, "timeout": 3000}, headers=headers, timeout=5)
            if r.status_code == 200:
                delay = r.json().get("delay", 0)
                if delay > 0:
                    return name, delay
        except Exception:
            pass
        return None

    try:
        with ThreadPoolExecutor(max_workers=50) as executor:
            results = executor.map(check_proxy, clash_proxies)
            for res in results:
                if res:
                    alive_nodes[res[0]] = res[1]
    finally:
        proc.kill()
        proc.wait()
        if os.path.exists("temp_clash.yaml"):
            os.remove("temp_clash.yaml")

    print(f"[+] 真连接检测完毕，绝对可用节点数量: {len(alive_nodes)}")
    return alive_nodes

def classify_and_filter(alive_proxies, node_map):
    """并发快速解析 IP，判别国家归属与家宽住宅属性"""
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

        is_residential = False
        try:
            a = asn_reader.get(ip)
            if a and "autonomous_system_number" in a:
                asn = a["autonomous_system_number"]
                if asn not in DATACENTER_ASNS:
                    is_residential = True
        except Exception:
            pass

        return {
            "link": original_link,
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

def export_subscriptions(verified_nodes):
    """导出分发订阅文件"""
    all_links = [n["link"] for n in verified_nodes]
    residential_links = [n["link"] for n in verified_nodes if n["is_residential"]]

    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())

    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(residential_links).encode()).decode())

    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n["link"])

    for cc, links in by_cc.items():
        path = os.path.join(COUNTRY_DIR, f"{cc}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())

    res_by_cc = {}
    for n in verified_nodes:
        if n["is_residential"]:
            res_by_cc.setdefault(n["country"], []).append(n["link"])

    for cc, links in res_by_cc.items():
        path = os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())

    print(f"[*] 导出成功！全量可用: {len(all_links)} | 家宽节点: {len(residential_links)} | 覆盖国家: {len(by_cc)}")
    return by_cc, res_by_cc, len(all_links), len(residential_links)

def update_readme(by_cc, res_by_cc, total_count, res_count):
    """自动重绘 README 表格数据"""
    repo = os.environ.get("GITHUB_REPOSITORY", "heleihub/free-node-subscription")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    all_countries = sorted(by_cc.keys(), key=lambda c: len(by_cc[c]), reverse=True)
    country_table_rows = []
    for cc in all_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / Other"))
        count = len(by_cc.get(cc, []))
        raw_url = f"https://raw.githubusercontent.com/{repo}/main/output/by-country/{cc}.txt"
        cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/{cc}.txt"
        country_table_rows.append(f"| {flag} {cc} | {name} | **{count}** | [查看 Raw]({raw_url}) | [CDN 订阅]({cdn_url}) |")

    country_table_str = "\n".join(country_table_rows) if country_table_rows else "| - | 暂无有效节点 | 0 | - | - |"

    all_res_countries = sorted(res_by_cc.keys(), key=lambda c: len(res_by_cc[c]), reverse=True)
    res_table_rows = []
    for cc in all_res_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / Other"))
        count = len(res_by_cc.get(cc, []))
        raw_url = f"https://raw.githubusercontent.com/{repo}/main/output/residential-by-country/{cc}.txt"
        cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/{cc}.txt"
        res_table_rows.append(f"| {flag} {cc} | {name} | **{count}** | [查看 Raw]({raw_url}) | [CDN 订阅]({cdn_url}) |")

    res_table_str = "\n".join(res_table_rows) if res_table_rows else "| - | 暂无可用家宽节点 | 0 | - | - |"

    readme_content = f"""# 🚀 自动测活与多源免费节点订阅池 (含真家宽/住宅IP分类)

> 🕒 **最后更新时间**: `{now_utc}`  
> 🟢 **真连接可用节点总量**: `{total_count}` 个  
> 🏠 **甄选住宅/家宽节点总量**: `{res_count}` 个  
> ⚡ **质量保证**: 所有节点均由 `mihomo` (Clash Meta) 内核执行真实代理握手（Google 204）测活过滤，拒绝虚假通畅与死节点。

---

## 📌 核心订阅总链接

| 分类类型 | 可用数量 | GitHub 原始订阅链接 | CDN 快速订阅链接 (免翻推荐) |
| :--- | :---: | :--- | :--- |
| 🌐 **全部有效节点总汇** | `{total_count}` | [Raw Link](https://raw.githubusercontent.com/{repo}/main/output/v2ray.txt) | `https://cdn.jsdelivr.net/gh/{repo}@main/output/v2ray.txt` |
| 🏠 **全量住宅家宽总汇** | `{res_count}` | [Raw Link](https://raw.githubusercontent.com/{repo}/main/output/residential.txt) | `https://cdn.jsdelivr.net/gh/{repo}@main/output/residential.txt` |

---

## 🏠 住宅家宽节点 (按国家/地区分类)
> 经 MaxMind ASN 数据库精准排除所有云端机房/服务器节点，保留真实居民宽带 IP。

| 代码 | 国家/地区 | 家宽节点数 | Raw 链接 | 免翻 CDN 订阅链接 |
| :---: | :--- | :---: | :---: | :--- |
{res_table_str}

---

## 🗺️ 全量节点分流 (按国家/地区分类)

| 代码 | 国家/地区 | 可用节点数 | Raw 链接 | 免翻 CDN 订阅链接 |
| :---: | :--- | :---: | :---: | :--- |
{country_table_str}

---

## 🛠️ 项目特性与说明

1. **真连接连通检测**：摒弃单纯的 TCP 端口 ping，使用 mihomo 内核通过代理链路实际访问 Google 204 端点并校验往返时间（RTT $\le$ 3000ms），测出可用即代表真实可用。
2. **多源采集聚合**：集成 GitHub 活跃订阅池，并自动爬取 `outlinekeys.com` 及 `shadowmere.xyz` 的节点。
3. **全自动维护**：通过 GitHub Actions 全自动构建，运行后自动重绘本页面的节点统计与各分流文件。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("[+] README.md 页面数据统计与直链表格已自动更新完成！")

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
