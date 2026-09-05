import os
import re
import sys
import json
import time
import base64
import shutil
import urllib.request
import subprocess
import requests
import yaml
import maxminddb
from concurrent.futures import ThreadPoolExecutor

# ----------------- 1. 从原仓库及上游逆向提取的核心节点源池 -----------------
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

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
os.makedirs(COUNTRY_DIR, exist_ok=True)

# 常见机房/数据中心云厂商 ASN（用于排除机房节点，保留家宽/住宅 IP）
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
}

def setup_environment():
    """下载 GeoIP/ASN 数据库及 mihomo (Clash Meta) 内核"""
    print("[*] 正在准备依赖环境与数据库...")
    if not os.path.exists("Country.mmdb"):
        urllib.request.urlretrieve("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb", "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        urllib.request.urlretrieve("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb", "ASN.mmdb")
    
    # 下载 Linux amd64 的 mihomo 内核
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
    """多渠道爬取原始节点"""
    nodes = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    print("[*] 正在从提取的源池拉取节点...")
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
                "server": data.get("add"),
                "port": int(data.get("port")),
                "uuid": data.get("id"),
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
    """使用 mihomo 内核批量并发真连接测试"""
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
    time.sleep(3)  # 等待内核启动并加载外部控制器

    alive_nodes = {}
    test_url = "http://cp.cloudflare.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            # 3000ms 超时限制，严格保证质量
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
    """解析落地国家与家宽住宅属性"""
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    for name, delay in alive_proxies.items():
        original_link, p_obj = node_map[name]
        server = p_obj["server"]
        try:
            ip = socket.gethostbyname(server)
        except Exception:
            continue

        # 国家代码解析
        country_code = "OTHER"
        try:
            c = country_reader.get(ip)
            if c and "country" in c:
                country_code = c["country"]["iso_code"]
        except Exception:
            pass

        # 家宽识别 (非 IDC 常见 ASN 即判定为住宅宽带)
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
    """写入分流订阅文件"""
    all_links = [n["link"] for n in verified_nodes]
    residential_links = [n["link"] for n in verified_nodes if n["is_residential"]]

    # 1. 全量真连通订阅
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())

    # 2. 家宽/住宅 IP 专属订阅
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(residential_links).encode()).decode())

    # 3. 按国家输出
    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n["link"])

    for cc, links in by_cc.items():
        path = os.path.join(COUNTRY_DIR, f"{cc}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())

    print(f"[*] 导出成功！全量可用: {len(all_links)} | 家宽节点: {len(residential_links)} | 覆盖国家: {len(by_cc)}")

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
    export_subscriptions(verified)
