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

# ----------------- 1. 订阅源池 -----------------
SOURCE_URLS = [
    "https://shadowmere.xyz/api/b64sub/",
    "https://shadowmere.xyz/api/sub/",
    "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/all.txt",
    "https://raw.githubusercontent.com/10ium/HiN-VPN/main/subscription/base64/mix",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/protocols/hysteria",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/security/tls",
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/v2ray-base64.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreGFW/master/subs/base64.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
]

SCRAPE_WEBSITES = [
    "https://outlinekeys.com/protocols/vless/",
    "https://shadowmere.xyz/api/vless",
    "https://shadowmere.xyz/",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RESIDENTIAL_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")
os.makedirs(COUNTRY_DIR, exist_ok=True)
os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)

VALID_SS_CIPHERS = {
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305", "aes-128-ctr", "aes-192-ctr",
    "aes-256-ctr", "aes-128-cfb", "aes-192-cfb", "aes-256-cfb", "rc4-md5"
}

DATACENTER_ASNS = {
    13335, 16509, 14618, 15169, 396982, 8075, 24940, 16276, 
    14061, 31898, 63949, 45102, 132203, 20473, 60068, 55081,
    197540, 51167, 8560, 42708, 201814, 49981, 212238, 46652,
    141995, 200019, 136907, 39351, 9009
}

RESIDENTIAL_ASNS = {
    3462, 9924, 9919, 17709, 4780, 17408, 18049,
    9304, 9269, 17816, 58453,
    2516, 17511, 2519, 2527, 4713, 9605, 17676, 2514,
    701, 702, 7922, 20115, 7018, 10796, 11427, 5650, 22773,
    2856, 5089, 5607, 13285, 5378,
    3320, 3209, 31334, 6805, 8881,
}

RESIDENTIAL_RDNS_KEYWORDS = [
    "dynamic", "broadband", "dsl", "dial", "pppoe", "pool", "user", 
    "cust", "home", "res", "dhcp", "ftth", "cable", "hinet-ip", "kbro"
]

DATACENTER_RDNS_KEYWORDS = [
    "vps", "server", "cloud", "compute", "datacenter", "hosting", "dedicated", "node"
]

COUNTRY_NAMES = {
    "HK": "香港",
    "TW": "台湾",
    "JP": "日本",
    "SG": "新加坡",
    "US": "美国",
    "KR": "韩国",
    "DE": "德国",
    "GB": "英国",
    "CA": "加拿大",
    "FR": "法国",
    "NL": "荷兰",
    "RU": "俄罗斯",
    "IN": "印度",
    "AU": "澳大利亚",
    "IT": "意大利",
    "ES": "西班牙",
    "TR": "土耳其",
    "AE": "阿联酋",
    "OTHER": "其他",
}

# 节点原始备注关键词匹配国家字典（防止 Anycast/Cloudflare 误杀）
NAME_COUNTRY_RULES = [
    ("HK", ["hk", "hongkong", "hong kong", "香港"]),
    ("TW", ["tw", "taiwan", "台湾", "台北", "hinet"]),
    ("JP", ["jp", "japan", "日本", "东京", "大阪"]),
    ("SG", ["sg", "singapore", "新加坡", "狮城"]),
    ("US", ["us", "united states", "usa", "美国", "洛杉矶", "硅谷"]),
    ("KR", ["kr", "korea", "韩国", "首尔"]),
    ("DE", ["de", "germany", "德国", "法兰克福"]),
    ("GB", ["gb", "uk", "united kingdom", "英国", "伦敦"]),
    ("CA", ["ca", "canada", "加拿大"]),
    ("FR", ["fr", "france", "法国", "巴黎"]),
    ("NL", ["nl", "netherlands", "荷兰", "阿姆斯特丹"]),
    ("RU", ["ru", "russia", "俄罗斯", "莫斯科"]),
]

def get_country_flag(country_code):
    if not country_code or country_code.upper() in ["OTHER", "ZZ", "XX", "T1"]:
        return "🌐"
    try:
        cc = country_code.upper()
        if len(cc) == 2 and cc.isalpha():
            return chr(ord(cc[0]) + 127397) + chr(ord(cc[1]) + 127397)
    except Exception:
        pass
    return "🌐"

def safe_download(url, dest_path):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def setup_environment():
    print("[*] 正在准备测活内核与离线数据库...")
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
    for _ in range(2):
        try:
            padded = text.strip() + '=' * (-len(text.strip()) % 4)
            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
            if any(p in decoded for p in ["vmess://", "vless://", "ss://", "trojan://", "hysteria2://"]):
                text += "\n" + decoded
        except Exception:
            pass

    pattern = r'((?:vmess|vless|ss|trojan|hysteria2|hy2)://[^\s"\'<>]+)'
    for m in re.findall(pattern, text):
        clean = m.strip().rstrip(".,;\"')")
        results.add(clean)
    return results

def fetch_raw_nodes():
    nodes = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*"
    }

    print("[*] 正在抓取全部节点源池...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=25)
            extracted = extract_nodes_from_text(resp.text)
            nodes.update(extracted)
            print(f"[+] 抓取成功: {url} -> 获得 {len(extracted)} 个节点")
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")

    for site in SCRAPE_WEBSITES:
        try:
            resp = requests.get(site, headers=headers, timeout=20)
            if resp.status_code == 200:
                extracted = extract_nodes_from_text(resp.text)
                nodes.update(extracted)
                print(f"[+] 网页提取成功: {site} -> 获得 {len(extracted)} 个节点")
        except Exception as e:
            print(f"[!] 网页提取失败 {site}: {e}")
            
    print(f"[*] 节点池初始去重总量: {len(nodes)} 个")
    return list(nodes)

def get_node_original_ps(node_str):
    """提取节点原本的备注名称，用于辅助判定国家"""
    try:
        if node_str.startswith("vmess://"):
            b64 = node_str[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            return str(data.get("ps", "")).lower()
        elif "#" in node_str:
            return urllib.parse.unquote(node_str.split("#", 1)[1]).lower()
    except Exception:
        pass
    return ""

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
                        "short-id": ""
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

        elif node_str.startswith("ss://"):
            raw = node_str[5:]
            server, port, password, cipher = "", 0, "", ""
            if "@" in raw:
                user_info, host_info = raw.split("@", 1)
                user_info += '=' * (-len(user_info) % 4)
                try:
                    dec = base64.b64decode(user_info).decode('utf-8', errors='ignore')
                    if ":" in dec:
                        cipher, password = dec.split(":", 1)
                except Exception:
                    pass
                host_info = host_info.split("#")[0]
                if ":" in host_info:
                    server, port_s = host_info.split(":", 1)
                    port_s = port_s.split("/")[0]
                    port = int(port_s) if port_s.isdigit() else 0
            else:
                raw_b64 = raw.split("#")[0].split("?")[0]
                raw_b64 += '=' * (-len(raw_b64) % 4)
                try:
                    dec = base64.b64decode(raw_b64).decode('utf-8', errors='ignore')
                    m_ss = re.search(r"([^:]+):([^@]+)@([^:]+):(\d+)", dec)
                    if m_ss:
                        cipher, password, server, port_s = m_ss.groups()
                        port = int(port_s)
                except Exception:
                    pass

            cipher = cipher.lower().strip()
            if cipher == "chacha20-poly1305":
                cipher = "chacha20-ietf-poly1305"
            
            if cipher in VALID_SS_CIPHERS and server and 0 < port <= 65535 and password:
                return {
                    "name": name,
                    "type": "ss",
                    "server": server.strip(),
                    "port": port,
                    "cipher": cipher,
                    "password": password.strip(),
                    "udp": True
                }

        elif node_str.startswith(("hysteria2://", "hy2://")):
            clean_url = node_str.replace("hy2://", "hysteria2://")
            parsed = urllib.parse.urlparse(clean_url)
            server = parsed.hostname
            port = parsed.port or 443
            auth = parsed.username or ""
            if server and 0 < port <= 65535:
                return {
                    "name": name,
                    "type": "hysteria2",
                    "server": server.strip(),
                    "port": int(port),
                    "password": auth,
                    "sni": server.strip(),
                    "skip-cert-verify": True
                }
    except Exception:
        pass
    return None

def test_single_batch(proxies_batch, port=19090, secret="secret123"):
    if not proxies_batch:
        return {}

    config = {
        "mixed-port": 17890,
        "mode": "rule",
        "log-level": "silent",
        "external-controller": f"127.0.0.1:{port}",
        "secret": secret,
        "proxies": proxies_batch
    }
    with open("temp_clash.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

    proc = subprocess.Popen(["./mihomo", "-d", ".", "-f", "temp_clash.yaml"])
    time.sleep(3)

    if proc.poll() is not None:
        if os.path.exists("temp_clash.yaml"):
            os.remove("temp_clash.yaml")
        return {}

    batch_alive = {}
    test_url = "http://cp.cloudflare.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            r = requests.get(url, params={"url": test_url, "timeout": 4500}, headers=headers, timeout=6)
            if r.status_code in [200, 204]:
                delay = r.json().get("delay", 0)
                if delay > 0:
                    return name, delay
        except Exception:
            pass
        return None

    try:
        with ThreadPoolExecutor(max_workers=60) as executor:
            results = executor.map(check_proxy, proxies_batch)
            for res in results:
                if res:
                    batch_alive[res[0]] = res[1]
    finally:
        proc.kill()
        proc.wait()
        if os.path.exists("temp_clash.yaml"):
            os.remove("temp_clash.yaml")

    return batch_alive

def run_real_delay_test(clash_proxies):
    if not clash_proxies:
        return {}

    total_proxies = len(clash_proxies)
    print(f"[*] 启动全量真连接测活，过滤后合规节点总量: {total_proxies} 个...")
    
    alive_nodes = {}
    batch_size = 1200
    for i in range(0, total_proxies, batch_size):
        batch = clash_proxies[i : i + batch_size]
        print(f"[*] 正在测活第 {i+1} ~ {min(i+batch_size, total_proxies)} 个节点...")
        res = test_single_batch(batch)
        alive_nodes.update(res)
        print(f"[+] 当前批次存活: {len(res)} 个 | 累计存活: {len(alive_nodes)} 个")

    print(f"[+] 全部节点检测完毕！真实存活总量: {len(alive_nodes)}")
    return alive_nodes

def rename_node_link(raw_link, new_name):
    try:
        if raw_link.startswith("vmess://"):
            b64 = raw_link[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            data["ps"] = new_name
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
            return f"vmess://{new_b64}"
        elif "#" in raw_link:
            base_url = raw_link.split("#")[0]
            return f"{base_url}#{urllib.parse.quote(new_name)}"
        else:
            return f"{raw_link}#{urllib.parse.quote(new_name)}"
    except Exception:
        return raw_link

def get_rdns_host(ip):
    try:
        socket.setdefaulttimeout(1.5)
        host, _, _ = socket.gethostbyaddr(ip)
        return host.lower()
    except Exception:
        return ""

def classify_and_filter(alive_proxies, node_map):
    """
    深度国家判断逻辑：
    1. 优先查 MaxMind Country.mmdb
    2. 若 IP 返回 T1/Anycast/OTHER，自动从节点原备注中正则匹配提取国家（消灭 OTHER）
    """
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    def resolve_and_classify(item):
        name, delay = item
        original_link, p_obj = node_map[name]
        server = p_obj["server"]
        orig_ps = get_node_original_ps(original_link)
        try:
            ip = socket.gethostbyname(server)
        except Exception:
            return None

        # 1. 尝试使用 MMDB 本地解析
        country_code = "OTHER"
        try:
            c = country_reader.get(ip)
            if c and "country" in c:
                code = c["country"]["iso_code"]
                if code not in ["T1", "A1", "A2", "OTHER"]:
                    country_code = code
        except Exception:
            pass

        # 2. 如果查出来是 OTHER/Anycast，回溯原备注里的国家特征进行精准提取
        if country_code == "OTHER":
            for target_cc, keywords in NAME_COUNTRY_RULES:
                if any(kw in orig_ps for kw in keywords):
                    country_code = target_cc
                    break

        # 3. 家宽判定
        is_residential = False
        try:
            a = asn_reader.get(ip)
            asn = a.get("autonomous_system_number", 0) if a else 0
            org = str(a.get("autonomous_system_organization", "")).lower() if a else ""
            
            if asn in RESIDENTIAL_ASNS:
                is_residential = True
            elif asn not in DATACENTER_ASNS:
                rdns = get_rdns_host(ip)
                if not any(k in rdns for k in DATACENTER_RDNS_KEYWORDS):
                    if any(k in rdns for k in RESIDENTIAL_RDNS_KEYWORDS):
                        is_residential = True
                    elif any(k in org for k in ["broadband", "consumer", "dsl", "ftth", "residential", "hinet", "chunghwa"]):
                        is_residential = True
        except Exception:
            pass

        return {
            "link": original_link,
            "clash_proxy": dict(p_obj),
            "country": country_code,
            "is_residential": is_residential,
            "delay": delay
        }

    print("[*] 正在解析可用节点的真实国家与家宽属性...")
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(resolve_and_classify, item) for item in alive_proxies.items()]
        for f in as_completed(futures):
            res = f.result()
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()
    return verified

def export_clash_yaml(clash_proxies, filepath):
    names = [p["name"] for p in clash_proxies]
    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": clash_proxies,
        "proxy-groups": [
            {"name": "PROXIES", "type": "select", "proxies": ["AUTO"] + names},
            {"name": "AUTO", "type": "url-test", "url": "http://cp.cloudflare.com/generate_204", "interval": 300, "proxies": names}
        ],
        "rules": ["MATCH,PROXIES"]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def export_singbox_json(clash_proxies, filepath):
    names = [p["name"] for p in clash_proxies]
    outbounds = [
        {"type": "selector", "tag": "select", "outbounds": ["auto"] + names},
        {"type": "urltest", "tag": "auto", "outbounds": names, "url": "http://cp.cloudflare.com/generate_204"},
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"}
    ]
    config = {"version": 1, "outbounds": outbounds}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def format_node_group(nodes_list, res_tag_force=False):
    """
    格式规范化：
    1. 带上真彩色国旗
    2. 带上中文国家名称（解决 Windows 字体渲染问题）
    3. 每个订阅独立从 01 开始依次编号
    4. 结尾加上 - xiaohe
    示例：🇹🇼 台湾 01 (家宽) - xiaohe / 🇯🇵 日本 02 - xiaohe
    """
    formatted_links = []
    formatted_proxies = []
    
    counters = {}
    for item in nodes_list:
        cc = item["country"]
        counters[cc] = counters.get(cc, 0) + 1
        idx = counters[cc]
        flag = get_country_flag(cc)
        c_name = COUNTRY_NAMES.get(cc, cc)
        
        is_res = item["is_residential"] or res_tag_force
        tag = " (家宽)" if is_res else ""
        
        # 终极规范命名
        node_name = f"{flag} {c_name} {idx:02d}{tag} - xiaohe"
        
        new_proxy = dict(item["clash_proxy"])
        new_proxy["name"] = node_name
        formatted_proxies.append(new_proxy)
        
        new_link = rename_node_link(item["link"], node_name)
        formatted_links.append(new_link)
        
    return formatted_links, formatted_proxies

def export_subscriptions(verified_nodes):
    residential_nodes = [n for n in verified_nodes if n["is_residential"]]

    # 1. 导出【全部节点】(从 01 开始编号)
    all_links, all_proxies = format_node_group(verified_nodes)
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())
    export_clash_yaml(all_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    export_singbox_json(all_proxies, os.path.join(OUTPUT_DIR, "singbox.json"))

    # 2. 导出【全量家宽节点】(从 01 开始重新连续编号)
    res_links, res_proxies = format_node_group(residential_nodes, res_tag_force=True)
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(res_links).encode()).decode())
    if res_proxies:
        export_clash_yaml(res_proxies, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
        export_singbox_json(res_proxies, os.path.join(OUTPUT_DIR, "residential-singbox.json"))

    # 3. 导出【按国家分类全部节点】(各国家单独从 01 开始排号)
    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in by_cc.items():
        c_links, c_proxies = format_node_group(n_list)
        with open(os.path.join(COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(c_links).encode()).decode())
        export_clash_yaml(c_proxies, os.path.join(COUNTRY_DIR, f"clash-{cc}.yaml"))

    # 4. 导出【按国家分类家宽节点】(各国家家宽单独从 01 开始排号)
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in res_by_cc.items():
        cr_links, cr_proxies = format_node_group(n_list, res_tag_force=True)
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(cr_links).encode()).decode())
        export_clash_yaml(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))

    print(f"[*] 导出完毕！全部存活: {len(all_links)} | 真家宽: {len(res_links)} | 涉及国家: {len(by_cc)}")
    return by_cc, res_by_cc, len(all_links), len(residential_links)

def update_readme():
    repo = os.environ.get("GITHUB_REPOSITORY", "heleihub/free-node-subscription")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def count_base64_file(path):
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return 0
                decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
                return len([line for line in decoded.splitlines() if line.strip()])
        except Exception:
            return 0

    total_count = count_base64_file(os.path.join(OUTPUT_DIR, "v2ray.txt"))
    res_count = count_base64_file(os.path.join(OUTPUT_DIR, "residential.txt"))

    country_counts = {}
    if os.path.exists(COUNTRY_DIR):
        for fname in os.listdir(COUNTRY_DIR):
            if fname.endswith(".txt"):
                cc = fname[:-4]
                cnt = count_base64_file(os.path.join(COUNTRY_DIR, fname))
                if cnt > 0:
                    country_counts[cc] = cnt

    res_country_counts = {}
    if os.path.exists(RESIDENTIAL_COUNTRY_DIR):
        for fname in os.listdir(RESIDENTIAL_COUNTRY_DIR):
            if fname.endswith(".txt"):
                cc = fname[:-4]
                cnt = count_base64_file(os.path.join(RESIDENTIAL_COUNTRY_DIR, fname))
                if cnt > 0:
                    res_country_counts[cc] = cnt

    # 生成家宽表格
    res_table_rows = []
    for cc in sorted(res_country_counts.keys(), key=lambda x: res_country_counts[x], reverse=True):
        flag = get_country_flag(cc)
        c_name = COUNTRY_NAMES.get(cc, cc)
        count = res_country_counts[cc]
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/clash-{cc}.yaml"
        res_table_rows.append(f"| {flag} {c_name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    res_table_str = "\n".join(res_table_rows) if res_table_rows else "| 暂无可用家宽节点 | 0 | - | - |"

    # 生成全量表格
    country_table_rows = []
    for cc in sorted(country_counts.keys(), key=lambda x: country_counts[x], reverse=True):
        flag = get_country_flag(cc)
        c_name = COUNTRY_NAMES.get(cc, cc)
        count = country_counts[cc]
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/clash-{cc}.yaml"
        country_table_rows.append(f"| {flag} {c_name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    country_table_str = "\n".join(country_table_rows) if country_table_rows else "| 暂无可用节点 | 0 | - | - |"

    readme_content = f"""# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 🕒 **最近更新时间**: `{now_utc}`  
> 🟢 **全部可用节点数量**: `{total_count}` 个  
> 🏠 **甄选家宽节点数量**: `{res_count}` 个  
> 👤 **定制规范命名**: 所有订阅节点均重命名为 `国旗 地区 序号 (家宽) - xiaohe`  
> ⚡ **真实可用保障**: 所有节点由 `mihomo` 代理内核建立实际网络通道握手测活，拒绝虚假通畅与死节点。

---

## 📌 全部节点总订阅链接 (支持 Clash / V2Ray / sing-box)

| 客户端 / 格式类型 | 节点总数 | 免翻 CDN 订阅直链 (复制到客户端直接使用) |
| :--- | :---: | :--- |
| 🚀 **Clash (YAML 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/clash.yaml` |
| ⚡ **V2Ray / 通用 Base64** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/v2ray.txt` |
| 📦 **sing-box (JSON 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo}@main/output/singbox.json` |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 经 MaxMind ASN 数据库与 rDNS 宽带特征探测，排除所有云主机/数据中心，保留真实民用宽带。

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
1. **自动更新机制**：GitHub Actions 每 6 小时全自动运行并刷新上述全部订阅与数据。
2. **多客户端兼容**：
   - **Clash / Clash Verge / Mihomo Party**：直接复制上方表格中的 **Clash 订阅** 链接。
   - **v2rayN / v2rayNG / Shadowrocket (小火箭)**：直接复制 **V2Ray/通用** 链接。
   - **sing-box**：直接使用上方 `singbox.json` 直链。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[+] README.md 数据更新完成！全部可用: {total_count}, 真家宽数: {res_count}")

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
    update_readme()
