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

SOURCE_URLS = [
    "https://shadowmere.xyz/api/b64sub/",
    "https://shadowmere.xyz/api/sub/",
    "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/all.txt",
    "https://raw.githubusercontent.com/10ium/HiN-VPN/main/subscription/base64/mix",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/protocols/hysteria",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/security/tls",
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/v2ray-base64.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RESIDENTIAL_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")

def ensure_directories():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(COUNTRY_DIR, exist_ok=True)
    os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)

ensure_directories()

VALID_SS_CIPHERS = {
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305", "aes-128-ctr", "aes-192-ctr",
    "aes-256-ctr", "aes-128-cfb", "aes-192-cfb", "aes-256-cfb", "rc4-md5"
}

# 扩充数据中心机房 ASN 黑名单，杜绝机房 IP 冒充家宽
DATACENTER_ASNS = {
    13335, 16509, 14618, 15169, 396982, 8075, 24940, 16276, 
    14061, 31898, 63949, 45102, 132203, 20473, 60068, 55081,
    197540, 51167, 8560, 42708, 201814, 49981, 212238, 46652,
    141995, 200019, 136907, 39351, 9009, 174, 3356, 1299, 2914
}

# 严格确认为真正民用宽带的 ASN 白名单
REAL_RESIDENTIAL_ASNS = {
    3462, 9924, 9919, 17709, 4780, 17408, 18049,  # 台湾 Chunghwa / Kbro
    9304, 9269, 17816, 58453,                      # 香港 HKBN / PCCW
    2516, 17511, 2519, 2527, 4713, 9605, 17676,    # 日本 KDDI / NTT / OCN / Softbank
    701, 702, 7922, 20115, 7018, 10796, 11427, 5650, 22773, # 美国 Comcast / AT&T / Charter
    2856, 5089, 5607, 13285, 5378,                 # 英国 BT / Sky / Virgin
    3320, 3209, 31334, 6805, 8881,                 # 德国 Deutsche Telekom / Vodafone
}

COUNTRY_NAMES = {
    "HK": "中国香港 (Hong Kong)",
    "TW": "中国台湾 (Taiwan)",
    "JP": "日本 (Japan)",
    "SG": "新加坡 (Singapore)",
    "US": "美国 (United States)",
    "KR": "韩国 (South Korea)",
    "DE": "德国 (Germany)",
    "GB": "英国 (United Kingdom)",
    "CA": "加拿大 (Canada)",
    "FR": "法国 (France)",
    "NL": "荷兰 (Netherlands)",
    "RU": "俄罗斯 (Russia)",
    "IN": "印度 (India)",
    "AU": "澳大利亚 (Australia)",
    "IT": "意大利 (Italy)",
    "ES": "西班牙 (Spain)",
    "TR": "土耳其 (Turkey)",
    "AE": "阿联酋 (UAE)",
    "OTHER": "其他地区 (Other)",
}

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
                return None, None

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
            # 强物理去重 Key: 相同 IP 和 端口坚决不重复出现
            unique_key = f"{server.lower()}:{port}"
            return proxy, unique_key

        elif node_str.startswith("vless://"):
            m = re.search(r"vless://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                uuid, server, port_s, query = m.groups()
                server = server.strip()
                port = int(port_s)
                uuid = uuid.strip()
                if not server or port <= 0 or port > 65535 or not uuid:
                    return None, None

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
                        return None, None
                    proxy["reality-opts"] = {"public-key": pbk, "short-id": ""}
                    proxy["servername"] = params.get("sni", server).strip()
                    proxy["client-fingerprint"] = params.get("fp", "chrome")
                if params.get("type") == "ws":
                    proxy["network"] = "ws"
                    proxy["ws-opts"] = {
                        "path": urllib.parse.unquote(params.get("path", "/")),
                        "headers": {"Host": params.get("host", server).strip()}
                    }
                unique_key = f"{server.lower()}:{port}"
                return proxy, unique_key

        elif node_str.startswith("trojan://"):
            m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if m:
                password, server, port_s, query = m.groups()
                server = server.strip()
                port = int(port_s)
                password = password.strip()
                if not server or port <= 0 or port > 65535 or not password:
                    return None, None

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
                unique_key = f"{server.lower()}:{port}"
                return proxy, unique_key

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
                unique_key = f"{server.lower()}:{port}"
                return {
                    "name": name,
                    "type": "ss",
                    "server": server.strip(),
                    "port": port,
                    "cipher": cipher,
                    "password": password.strip(),
                    "udp": True
                }, unique_key
    except Exception:
        pass
    return None, None

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
    # 使用 Cloudflare 与 Google 双重严格真实可用性验证，排除假活
    test_url = "http://connectivitycheck.gstatic.com/generate_204"
    headers = {"Authorization": f"Bearer {secret}"}

    def check_proxy(p):
        name = p["name"]
        url = f"http://127.0.0.1:{port}/proxies/{urllib.parse.quote(name)}/delay"
        try:
            r = requests.get(url, params={"url": test_url, "timeout": 2800}, headers=headers, timeout=4)
            if r.status_code in [200, 204]:
                delay = r.json().get("delay", 0)
                # 严格限制延迟在真实范围（50ms ~ 2500ms），排除瞬时 RST 产生的虚假延迟
                if 50 < delay < 2500:
                    return name, delay
        except Exception:
            pass
        return None

    try:
        with ThreadPoolExecutor(max_workers=50) as executor:
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
    print(f"[*] 启动全量深度真连接测活，物理独立节点数: {total_proxies} 个...")
    
    alive_nodes = {}
    batch_size = 1000
    for i in range(0, total_proxies, batch_size):
        batch = clash_proxies[i : i + batch_size]
        print(f"[*] 正在测活第 {i+1} ~ {min(i+batch_size, total_proxies)} 个节点...")
        res = test_single_batch(batch)
        alive_nodes.update(res)
        print(f"[+] 当前批次真实可用: {len(res)} 个 | 累计可用: {len(alive_nodes)} 个")

    print(f"[+] 全部检测完毕！真实可用总量: {len(alive_nodes)}")
    return alive_nodes

def rename_node_link(raw_link, new_name):
    try:
        if raw_link.startswith("vmess://"):
            b64 = raw_link[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            data["ps"] = new_name
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
        elif any(raw_link.startswith(p) for p in ["vless://", "trojan://", "ss://", "hy2://", "hysteria2://"]):
            base_part = raw_link.split("#")[0].strip()
            return f"{base_part}#{urllib.parse.quote(new_name)}"
    except Exception:
        pass
    return raw_link

def get_rdns_host(ip):
    try:
        socket.setdefaulttimeout(1.2)
        host, _, _ = socket.gethostbyaddr(ip)
        return host.lower()
    except Exception:
        return ""

def classify_and_filter(alive_proxies, node_map):
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    def resolve_and_classify(item):
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
                code = c["country"]["iso_code"]
                if code not in ["T1", "A1", "A2", "OTHER"]:
                    country_code = code.upper()
        except Exception:
            pass

        # 更加严密的家宽判断逻辑：必须匹配真实运营商 ASN，彻底排除机房 IP 冒充家宽
        is_residential = False
        try:
            a = asn_reader.get(ip)
            asn = a.get("autonomous_system_number", 0) if a else 0
            org = str(a.get("autonomous_system_organization", "")).lower() if a else ""
            
            if asn in REAL_RESIDENTIAL_ASNS:
                is_residential = True
            elif asn not in DATACENTER_ASNS:
                rdns = get_rdns_host(ip)
                if any(k in rdns for k in ["broadband", "dynamic", "pppoe", "cust", "dial", "hinet-ip"]):
                    is_residential = True
                elif any(k in org for k in ["broadband", "chunghwa", "consumer", "hinet"]):
                    is_residential = True
        except Exception:
            pass

        return {
            "link": original_link,
            "clash_proxy": dict(p_obj),
            "country": str(country_code).upper(),
            "is_residential": is_residential,
            "server_ip": ip,
            "port": p_obj["port"],
            "delay": delay
        }

    print("[*] 正在解析出口国家与真家宽反向属性...")
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(resolve_and_classify, item) for item in alive_proxies.items()]
        for f in as_completed(futures):
            res = f.result()
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()

    # 最终防御：在入库前以 (server_ip, port) 做最终唯一性锁定，绝不允许任何重复节点出库！
    unique_verified = []
    seen_endpoints = set()
    for item in verified:
        endpoint = f"{item['server_ip']}:{item['port']}"
        if endpoint not in seen_endpoints:
            seen_endpoints.add(endpoint)
            unique_verified.append(item)

    return unique_verified

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
    formatted_links = []
    formatted_proxies = []
    
    for idx, item in enumerate(nodes_list, start=1):
        cc = item["country"]
        flag = get_country_flag(cc)
        c_name = COUNTRY_NAMES.get(cc, cc)
        
        is_res = item["is_residential"] or res_tag_force
        tag = " (家宽)" if is_res else ""
        
        node_name = f"{flag} {c_name} {idx:02d}{tag} - xiaohe"
        
        new_proxy = dict(item["clash_proxy"])
        new_proxy["name"] = node_name
        formatted_proxies.append(new_proxy)
        
        new_link = rename_node_link(item["link"], node_name)
        formatted_links.append(new_link)
        
    return formatted_links, formatted_proxies

def export_subscriptions(verified_nodes):
    ensure_directories()
    residential_nodes = [n for n in verified_nodes if n["is_residential"]]
    non_residential_nodes = [n for n in verified_nodes if not n["is_residential"]]

    # 1. 导出全量总订阅
    all_links, all_proxies = format_node_group(verified_nodes)
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())
    export_clash_yaml(all_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    export_singbox_json(all_proxies, os.path.join(OUTPUT_DIR, "singbox.json"))

    # 2. 导出家宽总订阅
    res_links, res_proxies = format_node_group(residential_nodes, res_tag_force=True)
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(res_links).encode()).decode())
    if res_proxies:
        export_clash_yaml(res_proxies, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
        export_singbox_json(res_proxies, os.path.join(OUTPUT_DIR, "residential-singbox.json"))

    # 3. 按国家分类【非家宽】
    by_cc = {}
    for n in non_residential_nodes:
        by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in by_cc.items():
        c_links, c_proxies = format_node_group(n_list)
        with open(os.path.join(COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(c_links).encode()).decode())
        export_clash_yaml(c_proxies, os.path.join(COUNTRY_DIR, f"clash-{cc}.yaml"))
        export_singbox_json(c_proxies, os.path.join(COUNTRY_DIR, f"singbox-{cc}.json"))

    # 4. 按国家分类【真家宽】
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in res_by_cc.items():
        cr_links, cr_proxies = format_node_group(n_list, res_tag_force=True)
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(cr_links).encode()).decode())
        export_clash_yaml(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))
        export_singbox_json(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"singbox-{cc}.json"))

    print(f"[*] 最终导出完毕！全量去重真活: {len(all_links)} | 家宽真活: {len(res_links)}")
    return len(all_links), len(res_links)

def update_readme():
    repo_name = os.environ.get("GITHUB_REPOSITORY", "heleihub/Free-node-subscription").strip()
    
    def count_file(path):
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                c = f.read().strip()
                if not c:
                    return 0
                decoded = base64.b64decode(c).decode("utf-8", errors="ignore")
                return len([line for line in decoded.splitlines() if line.strip()])
        except Exception:
            return 0

    total_count = count_file(os.path.join(OUTPUT_DIR, "v2ray.txt"))
    res_count = count_file(os.path.join(OUTPUT_DIR, "residential.txt"))

    res_counts = {}
    if os.path.exists(RESIDENTIAL_COUNTRY_DIR):
        for fn in os.listdir(RESIDENTIAL_COUNTRY_DIR):
            if fn.endswith(".txt"):
                cc = fn[:-4]
                cnt = count_file(os.path.join(RESIDENTIAL_COUNTRY_DIR, fn))
                if cnt > 0:
                    res_counts[cc] = cnt

    normal_counts = {}
    if os.path.exists(COUNTRY_DIR):
        for fn in os.listdir(COUNTRY_DIR):
            if fn.endswith(".txt"):
                cc = fn[:-4]
                cnt = count_file(os.path.join(COUNTRY_DIR, fn))
                if cnt > 0:
                    normal_counts[cc] = cnt

    res_rows = []
    for cc in sorted(res_counts.keys(), key=lambda x: res_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, cc)
        cnt = res_counts[cc]
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/{cc}.txt"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/clash-{cc}.yaml"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/singbox-{cc}.json"
        sb_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/singbox-{cc}.json"

        col_v2 = f"[CDN 直链]({v2_cdn}) · [Raw 直链]({v2_raw})"
        col_clash = f"[CDN 直链]({clash_cdn}) · [Raw 直链]({clash_raw})"
        col_sb = f"[CDN 直链]({sb_cdn}) · [Raw 直链]({sb_raw})"
        res_rows.append(f"| {flag} {name} | {cnt} | {col_v2} | {col_clash} | {col_sb} |")
    res_table_str = "\n".join(res_rows) if res_rows else "| 暂无可用家宽节点 | 0 | - | - | - |"

    normal_rows = []
    for cc in sorted(normal_counts.keys(), key=lambda x: normal_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, cc)
        cnt = normal_counts[cc]
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/{cc}.txt"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/clash-{cc}.yaml"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/singbox-{cc}.json"
        sb_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/singbox-{cc}.json"

        col_v2 = f"[CDN 直链]({v2_cdn}) · [Raw 直链]({v2_raw})"
        col_clash = f"[CDN 直链]({clash_cdn}) · [Raw 直链]({clash_raw})"
        col_sb = f"[CDN 直链]({sb_cdn}) · [Raw 直链]({sb_raw})"
        normal_rows.append(f"| {flag} {name} | {cnt} | {col_v2} | {col_clash} | {col_sb} |")
    normal_table_str = "\n".join(normal_rows) if normal_rows else "| 暂无可用节点 | 0 | - | - | - |"

    worker_code = """```javascript
export default {
  async fetch(request) {
    const GITHUB_TOKEN = "ghp_你的GitHub永久访问令牌"; // 填入第1步生成的Token
    const OWNER = "heleihub";
    const REPO = "Free-node-subscription";
    const BRANCH = "main";

    const url = new URL(request.url);
    const filePath = "output" + url.pathname;
    const ghUrl = "[https://raw.githubusercontent.com/](https://raw.githubusercontent.com/)" + OWNER + "/" + REPO + "/" + BRANCH + "/" + filePath;
    
    const res = await fetch(ghUrl, {
      headers: {
        "Authorization": "token " + GITHUB_TOKEN,
        "User-Agent": "Cloudflare-Worker"
      }
    });

    if (!res.ok) {
      return new Response("Not Found", { status: 404 });
    }

    return new Response(await res.text(), {
      headers: { 
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache" 
      }
    });
  }
}
```"""

    readme_content = f"""# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 👤 **定制规范命名**: 所有订阅节点均重命名为 `国旗 地区 序号 (家宽) - xiaohe`  
> ⚡ **真实可用保障**: 所有节点由 `mihomo` 代理内核建立实际网络通道握手测活，拒绝虚假通畅与死节点。无论是通过免翻 CDN 直链还是官方原生 Raw 直链拉取，节点命名格式完全一致。

---

## 📌 全部节点总订阅链接

| 客户端 / 格式类型 | 节点总数 | 免翻 CDN 订阅直链 (国内直连) | 官方原生 Raw 直链 (开启代理) |
| :--- | :---: | :--- | :--- |
| 🚀 **Clash (YAML 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/clash.yaml` | `https://raw.githubusercontent.com/{repo_name}/main/output/clash.yaml` |
| ⚡ **V2RayN (Base64 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/v2ray.txt` | `https://raw.githubusercontent.com/{repo_name}/main/output/v2ray.txt` |
| 📦 **sing-box (JSON 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/singbox.json` | `https://raw.githubusercontent.com/{repo_name}/main/output/singbox.json` |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 经 MaxMind ASN 数据库与 rDNS 宽带特征探测，排除所有云主机/数据中心，保留真实民用宽带。

| 家宽地区 | 节点数 | V2RayN 专属订阅 | Clash 专属订阅 | sing-box 专属订阅 |
| :--- | :---: | :---: | :---: | :---: |
{res_table_str}

---

## 🗺️ 按照国家分类节点订阅 (非家宽/数据中心节点)

| 地区/国家 | 节点数 | V2RayN 专属订阅 | Clash 专属订阅 | sing-box 专属订阅 |
| :--- | :---: | :---: | :---: | :---: |
{normal_table_str}

---

## 🔒 私有仓库（Private）无感免翻订阅方案 (基于 Cloudflare Workers)

> 如果你希望将本 GitHub 仓库设置为 **Private (私有仓库)** 保护节点资产，外部客户端无法直接拉取原生 Raw 或公共 CDN 链接，可以通过以下 Cloudflare Worker 搭建轻量级私密网关反代：

### 1. 获取 GitHub 永久个人令牌 (PAT)
1. 进入 GitHub -> **Settings** -> **Developer Settings** -> **Personal access tokens (classic)**。
2. 点击 **Generate new token (classic)**，勾选 `repo` 权限，有效期设为 `No expiration`（永不过期）。
3. 复制保存生成的以 `ghp_` 开头的 Token。

### 2. 部署 Cloudflare Worker
登录 Cloudflare Dashboard，创建一个新的 Worker，复制以下脚本粘贴并部署：

{worker_code}

### 3. 私有订阅链接映射方式
部署后 Worker 会分配一个专属域名（例如 `my-sub.yourname.workers.dev`），你的客户端可以直接无感订阅：
* **总 V2RayN 订阅**: `https://你的域名.workers.dev/v2ray.txt`
* **总 Clash 订阅**: `https://你的域名.workers.dev/clash.yaml`
* **总 sing-box 订阅**: `https://你的域名.workers.dev/singbox.json`
* **台湾家宽 V2RayN**: `https://你的域名.workers.dev/residential-by-country/TW.txt`
* **香港家宽 Clash**: `https://你的域名.workers.dev/residential-by-country/clash-HK.yaml`
* **日本家宽 sing-box**: `https://你的域名.workers.dev/residential-by-country/singbox-JP.json`

---

## ⭐ 项目热度

[![Star History Chart](https://api.star-history.com/svg?repos={repo_name}&type=Date)](https://star-history.com/#{repo_name}&Date)

---

## 🛠️ 项目使用说明
1. **自动更新机制**：GitHub Actions 每 6 小时全自动运行并刷新上述全部订阅与数据。
2. **多客户端兼容**：
   - **Clash / Clash Verge / Mihomo Party**：直接复制上方表格中的 **Clash 专属订阅** 链接。
   - **v2rayN / v2rayNG**：直接复制上方表格中的 **V2RayN 专属订阅** 链接。
   - **sing-box**：直接使用上方 **sing-box 专属订阅** 链接。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[+] README.md 实时动态表格更新完毕！总节点: {total_count}, 家宽节点: {res_count}")

if __name__ == "__main__":
    setup_environment()
    raw_nodes = fetch_raw_nodes()

    clash_list = []
    node_map = {}
    seen_endpoints = set()

    # 协议物理层去重：同一 IP + 同一端口只留一个
    for i, raw in enumerate(raw_nodes):
        c_obj, u_key = convert_node_to_clash(raw, i)
        if c_obj and u_key:
            if u_key not in seen_endpoints:
                seen_endpoints.add(u_key)
                clash_list.append(c_obj)
                node_map[c_obj["name"]] = (raw, c_obj)

    print(f"[*] 严格去重完成，真实独立端点数: {len(clash_list)}")
    alive_dict = run_real_delay_test(clash_list)
    verified = classify_and_filter(alive_dict, node_map)
    export_subscriptions(verified)
    update_readme()
