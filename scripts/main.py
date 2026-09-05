import os
import re
import base64
import socket
import urllib.request
import requests
import yaml
import maxminddb
from concurrent.futures import ThreadPoolExecutor

# ----------------- 公开订阅源池 -----------------
SOURCE_URLS = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreGFW/master/subs/base64.txt",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
os.makedirs(COUNTRY_DIR, exist_ok=True)

# 常见机房/数据中心云厂商 ASN 列表（用于排除机房节点，保留家宽/住宅 IP）
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
    20473,          # Choopa / Vultr
    60068,          # CDN77
    55081,          # 24-7
}

def download_geoip_dbs():
    """下载免费离线 GeoIP 与 ASN 数据库"""
    print("[*] 检查 GeoIP 与 ASN 数据库...")
    country_url = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
    asn_url = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb"
    if not os.path.exists("Country.mmdb"):
        print("[*] 正在下载 Country.mmdb...")
        urllib.request.urlretrieve(country_url, "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        print("[*] 正在下载 ASN.mmdb...")
        urllib.request.urlretrieve(asn_url, "ASN.mmdb")

def fetch_raw_nodes():
    """抓取并去重所有原始节点链接"""
    raw_nodes = set()
    print("[*] 开始拉取公共订阅源...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, timeout=15)
            content = resp.text.strip()
            # 兼容 Base64 编码的订阅内容
            try:
                decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                lines = decoded.splitlines()
            except Exception:
                lines = content.splitlines()

            for line in lines:
                line = line.strip()
                if any(line.startswith(p) for p in ["vmess://", "vless://", "ss://", "trojan://"]):
                    raw_nodes.add(line)
        except Exception as e:
            print(f"[!] 抓取 {url} 失败: {e}")
    print(f"[*] 成功收集到 {len(raw_nodes)} 个待测原始节点")
    return list(raw_nodes)

def parse_node(node_str):
    """解析节点的目标服务器地址和端口"""
    try:
        if node_str.startswith("vmess://"):
            b64_data = node_str[8:]
            b64_data += '=' * (-len(b64_data) % 4)
            import json
            data = json.loads(base64.b64decode(b64_data).decode('utf-8', errors='ignore'))
            return data.get("add"), int(data.get("port")), node_str
        elif any(node_str.startswith(p) for p in ["vless://", "trojan://"]):
            match = re.search(r"@([^:]+):(\d+)", node_str)
            if match:
                return match.group(1), int(match.group(2)), node_str
        elif node_str.startswith("ss://"):
            match = re.search(r"@([^:]+):(\d+)", node_str)
            if match:
                return match.group(1), int(match.group(2)), node_str
    except Exception:
        pass
    return None, None, node_str

def test_connectivity(host, port, timeout=2.5):
    """真连接握手检测：测试服务器端口是否通畅"""
    try:
        ip = socket.gethostbyname(host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.close()
        return ip
    except Exception:
        return None

def analyze_and_verify(nodes):
    """并发测活并进行国家代码和家宽属性判断"""
    verified = []
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")

    def worker(node_str):
        host, port, original = parse_node(node_str)
        if not host or not port:
            return None
        
        resolved_ip = test_connectivity(host, port)
        if not resolved_ip:
            return None

        # 1. 国家分类判定 (ISO-3166)
        country_code = "OTHER"
        try:
            c_info = country_reader.get(resolved_ip)
            if c_info and "country" in c_info:
                country_code = c_info["country"]["iso_code"]
        except Exception:
            pass

        # 2. 家宽/住宅 IP 判定
        is_residential = False
        try:
            a_info = asn_reader.get(resolved_ip)
            if a_info and "autonomous_system_number" in a_info:
                asn = a_info["autonomous_system_number"]
                if asn not in DATACENTER_ASNS:
                    is_residential = True
        except Exception:
            pass

        return {
            "link": original,
            "country": country_code,
            "is_residential": is_residential,
            "ip": resolved_ip
        }

    print("[*] 正在启动并发测活与属性识别 (线程池大小: 60)...")
    with ThreadPoolExecutor(max_workers=60) as executor:
        results = executor.map(worker, nodes)
        for res in results:
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()
    print(f"[*] 测活完成！存活有效节点: {len(verified)}")
    return verified

def export_results(verified_nodes):
    """导出分发文件：全量Base64订阅、家宽专属订阅、国家分类订阅"""
    all_links = [n["link"] for n in verified_nodes]
    residential_links = [n["link"] for n in verified_nodes if n["is_residential"]]

    # 1. 全量有效节点 Base64
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        b64_str = base64.b64encode("\n".join(all_links).encode("utf-8")).decode("utf-8")
        f.write(b64_str)

    # 2. 家宽专属节点 Base64
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        res_b64 = base64.b64encode("\n".join(residential_links).encode("utf-8")).decode("utf-8")
        f.write(res_b64)

    # 3. 各国独立分类文件
    country_groups = {}
    for n in verified_nodes:
        country_groups.setdefault(n["country"], []).append(n["link"])

    for cc, links in country_groups.items():
        file_path = os.path.join(COUNTRY_DIR, f"{cc}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode("utf-8")).decode("utf-8"))

    print(f"[*] 订阅文件导出成功！包含家宽节点: {len(residential_links)} 个，涉及 {len(country_groups)} 个国家/地区")

if __name__ == "__main__":
    download_geoip_dbs()
    raw_nodes = fetch_raw_nodes()
    verified_nodes = analyze_and_verify(raw_nodes)
    export_results(verified_nodes)
