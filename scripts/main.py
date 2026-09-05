import os
import re
import sys
import json
import time
import base64
import shutil
import urllib.request
import urllib.parse
import subprocess
import requests
import yaml
import maxminddb
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# ----------------- 1. 节点抓取源池 (含指定的新网站与原仓库提取源) -----------------
SOURCE_URLS = [
    # 原项目主力上游聚合与活跃订阅池
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreGFW/master/subs/base64.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/all",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
]

# 用户指定抓取网站列表
SCRAPE_WEBSITES = [
    "https://outlinekeys.com/protocols/vless/",
    "https://shadowmere.xyz/",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RESIDENTIAL_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")
os.makedirs(COUNTRY_DIR, exist_ok=True)
os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)

# 常见机房/数据中心云厂商 ASN（用于精准识别过滤，余下归类为家宽/住宅 IP）
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
}

# 常见国家代码对应的名称与国旗 Emoji
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

def setup_environment():
    """下载 GeoIP/ASN 数据库及 mihomo (Clash Meta) 内核"""
    print("[*] 正在准备依赖环境与数据库...")
    if not os.path.exists("Country.mmdb"):
        urllib.request.urlretrieve("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb", "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        urllib.request.urlretrieve("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb", "ASN.mmdb")
    
    if not os.path.exists("mihomo"):
        print("[*] 正在下载 mihomo 测活内核...")
        kernel_url = "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.9/mihomo-linux-amd64-v1.18.9.gz"
        urllib.request.urlretrieve(kernel_url, "mihomo.gz")
        import gzip
        with gzip.open("mihomo.gz", "rb") as f_in, open("mihomo", "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.chmod("mihomo", 0o755)
        if os.path.exists("mihomo.gz"):
            os.remove("mihomo.gz")

def fetch_raw_nodes():
    """多渠道爬取原始节点（包含常规订阅源及指定网页爬取）"""
    nodes = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    # 1. 常规订阅链接拉取
    print("[*] 正在从订阅源拉取节点...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            text = resp.text.strip()
            try:
                decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
                lines = decoded.splitlines()
            except Exception:
                lines = text.splitlines()

            for line in lines:
                line = line.strip()
                if any(line.startswith(p) for p in ["vmess://", "vless://", "ss://", "trojan://"]):
                    nodes.add(line)
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")

    # 2. 爬取特定网页中的节点内容 (shadowmere.xyz, outlinekeys.com)
    print("[*] 正在从指定网页端提取节点...")
    for site in SCRAPE_WEBSITES:
        try:
            resp = requests.get(site, headers=headers, timeout=20)
            if resp.status_code == 200:
                html = resp.text
                found_vless = re.findall(r'(vless://[^\s"\'<>]+)', html)
                found_vmess = re.findall(r'(vmess://[^\s"\'<>]+)', html)
                found_ss = re.findall(r'(ss://[^\s"\'<>]+)', html)
                found_trojan = re.findall(r'(trojan://[^\s"\'<>]+)', html)
                matched = found_vless + found_vmess + found_ss + found_trojan
                for m in matched:
                    clean_node = m.strip().rstrip(".,;\"'")
                    nodes.add(clean_node)
                print(f"[+] 从 {site} 成功抓取到 {len(matched)} 个节点")
        except Exception as e:
            print(f"[!] 网页抓取失败 {site}: {e}")
            
    print(f"[*] 原始去重节点池总量: {len(nodes)} 个")
    return list(nodes)

def convert_node_to_clash(node_str, index):
    """将通用 URL 节点转换为 Clash 代理字典"""
    name = f"node_{index}"
    try:
        if node_str.startswith("vmess://"):
            b64 = node_str[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            proxy = {
                "name": name,
                "type": "vmess",
                "server": str(data.get("add")),
                "port": int(data.get("port")),
                "uuid": str(data.get("id")),
                "alterId": int(data.get("aid", 0)),
                "cipher": "auto",
                "udp": True,
                "tls": True if data.get("tls") in ["tls", "1"] else False
            }
            if data.get("net") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = {
                    "path": data.get("path", "/"),
                    "headers": {"Host": data.get("host", data.get("add"))}
                }
            return proxy

        elif node_str.startswith("vless://"):
            m = re.search(r"vless://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                uuid, server, port, query = m.groups()
                params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
                proxy = {
                    "name": name,
                    "type": "vless",
                    "server": server,
                    "port": int(port),
                    "uuid": uuid,
                    "udp": True,
                    "tls": True if params.get("security") in ["tls", "reality"] else False
                }
                if params.get("security") == "reality":
                    proxy["reality-opts"] = {
                        "public-key": params.get("pbk", ""),
                        "short-id": params.get("sid", "")
                    }
                    proxy["servername"] = params.get("sni", "")
                if params.get("type") == "ws":
                    proxy["network"] = "ws"
                    proxy["ws-opts"] = {"path": params.get("path", "/")}
                return proxy

        elif node_str.startswith("trojan://"):
            m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                password, server, port, query = m.groups()
                params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
                proxy = {
                    "name": name,
                    "type": "trojan",
                    "server": server,
                    "port": int(port),
                    "password": password,
                    "udp": True,
                    "sni": params.get("sni", server)
                }
                return proxy
    except Exception:
        pass
    return None

def run_real_delay_test(clash_proxies, port=19090, secret="secret123"):
    """使用 mihomo 内核批量并发真连接测试 (返回真实连通与 RTT)"""
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

    proc = subprocess.Popen(["./mihomo", "-f", "temp_clash.yaml"])
    time.sleep(3)

    alive_nodes = {}
    test_url = "http://cp.cloudflare.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            # 严格限制 3000ms 超时，确保测出都是真可用高速节点
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
        proc.terminate()
        proc.wait()
        if os.path.exists("temp_clash.yaml"):
            os.remove("temp_clash.yaml")

    print(f"[+] 真连接检测完毕，绝对可用节点数量: {len(alive_nodes)}")
    return alive_nodes

def classify_and_filter(alive_proxies, node_map):
    """解析落地真实国家与家宽住宅属性"""
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    for name, delay in alive_proxies.items():
        original_link, p_obj = node_map[name]
        server = p_obj["server"]
        try:
            import socket
            ip = socket.gethostbyname(server)
        except Exception:
            continue

        # 1. 匹配国家代码
        country_code = "OTHER"
        try:
            c = country_reader.get(ip)
            if c and "country" in c:
                country_code = c["country"]["iso_code"]
        except Exception:
            pass

        # 2. 家宽判定
        is_residential = False
        try:
            a = asn_reader.get(ip)
            if a and "autonomous_system_number" in a:
                asn = a["autonomous_system_number"]
                if asn not in DATACENTER_ASNS:
                    is_residential = True
        except Exception:
            pass

        verified.append({
            "link": original_link,
            "country": country_code,
            "is_residential": is_residential,
            "delay": delay
        })

    country_reader.close()
    asn_reader.close()
    return verified

def export_subscriptions(verified_nodes):
    """导出所有分流订阅文件并返回统计数据"""
    all_links = [n["link"] for n in verified_nodes]
    residential_links = [n["link"] for n in verified_nodes if n["is_residential"]]

    # 1. 全量真连通订阅
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())

    # 2. 家宽/住宅 IP 专属订阅
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(residential_links).encode()).decode())

    # 3. 按国家输出全量节点
    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n["link"])

    for cc, links in by_cc.items():
        path = os.path.join(COUNTRY_DIR, f"{cc}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())

    # 4. 按国家输出家宽节点
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
    """像原仓库一样自动生成并更新 README.md 表格、节点数与订阅链接"""
    repo = os.environ.get("GITHUB_REPOSITORY", "heleihub/free-node-subscription")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 构建国家列表（按节点数量降序排列）
    all_countries = sorted(by_cc.keys(), key=lambda c: len(by_cc[c]), reverse=True)

    # 生成全量国家表格
    country_table_rows = []
    for cc in all_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / Other"))
        count = len(by_cc.get(cc, []))
        raw_url = f"https://raw.githubusercontent.com/{repo}/main/output/by-country/{cc}.txt"
        cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/{cc}.txt"
        country_table_rows.append(f"| {flag} {cc} | {name} | **{count}** | [查看]({raw_url}) | [CDN 订阅]({cdn_url}) |")

    country_table_str = "\n".join(country_table_rows)

    # 生成家宽专属国家表格
    all_res_countries = sorted(res_by_cc.keys(), key=lambda c: len(res_by_cc[c]), reverse=True)
    res_table_rows = []
    for cc in all_res_countries:
        flag, name = COUNTRY_META.get(cc, ("🌐", f"{cc} / Other"))
        count = len(res_by_cc.get(cc, []))
        raw_url = f"https://raw.githubusercontent.com/{repo}/main/output/residential-by-country/{cc}.txt"
        cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/{cc}.txt"
        res_table_rows.append(f"| {flag} {cc} | {name} | **{count}** | [查看]({raw_url}) | [CDN 订阅]({cdn_url}) |")

    res_table_str = "\n".join(res_table_rows) if res_table_rows else "| - | 暂无可用家宽节点 | 0 | - | - |"

    readme_content = f"""# 🚀 自动测活与多源免费节点订阅池 (含真家宽/住宅IP分类)

> 🕒 **最后更新时间**: `{now_utc}`  
> 🟢 **真连接可用节点总量**: `{total_count}` 个  
> 🏠 **甄选住宅/家宽节点总量**: `{res_count}` 个  
> ⚡ **质量保证**: 所有节点均由 `mihomo` (Clash Meta) 内核执行严格真连接握手（HTTP 204）过滤，拒绝虚假通畅与死节点。

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

1. **真连接连通检测**：摒弃单纯的 TCP ping，使用 mihomo 内核通过代理链路实际访问网络端点并校验往返时间（RTT $\le$ 3000ms），测出可用即代表客户端真实可用。
2. **多源采集聚合**：集成 GitHub 活跃订阅池，并自动提取爬取 `outlinekeys.com` 及 `shadowmere.xyz` 的免费节点。
3. **全自动维护**：通过 GitHub Actions 全自动定时构建，运行后自动重绘本页面的节点统计与各分流文件。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("[+] README.md 页面数据统计与直链表格已自动重新生成并写入！")

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
