import os
import re
import sys
import json
import time
import uuid
import zipfile
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

DATACENTER_ASNS = {
    13335, 16509, 14618, 15169, 396982, 8075, 24940, 16276, 
    14061, 31898, 63949, 45102, 132203, 20473, 60068, 55081,
    197540, 51167, 8560, 42708, 201814, 49981, 212238, 46652,
    141995, 200019, 136907, 39351, 9009, 174, 3356, 1299, 2914
}

REAL_RESIDENTIAL_ASNS = {
    3462, 9924, 9919, 17709, 4780, 17408, 18049,
    9304, 9269, 17816, 58453,
    2516, 17511, 2519, 2527, 4713, 9605, 17676,
    701, 702, 7922, 20115, 7018, 10796, 11427, 5650, 22773,
    2856, 5089, 5607, 13285, 5378,
    3320, 3209, 31334, 6805, 8881,
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def setup_environment():
    print("[*] 正在准备测活依赖与离线数据库...")
    if not os.path.exists("Country.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb", "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb", "ASN.mmdb")
    
    if not os.path.exists("xray"):
        print("[*] 正在下载官方 Xray-core 测活内核...")
        safe_download("https://github.com/XTLS/Xray-core/releases/download/v1.8.24/Xray-linux-64.zip", "xray.zip")
        with zipfile.ZipFile("xray.zip", 'r') as zip_ref:
            zip_ref.extract("xray", ".")
        os.chmod("xray", 0o755)
        if os.path.exists("xray.zip"):
            os.remove("xray.zip")

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
    headers = {"User-Agent": "Mozilla/5.0"}
    print("[*] 正在抓取节点池...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            extracted = extract_nodes_from_text(resp.text)
            nodes.update(extracted)
            print(f"[+] 抓取成功: {url} -> 获得 {len(extracted)} 个节点")
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")
    print(f"[*] 初始去重总量: {len(nodes)} 个")
    return list(nodes)

def resolve_host_cached(host, cache={}):
    if host in cache:
        return cache[host]
    try:
        socket.setdefaulttimeout(1.5)
        ip = socket.gethostbyname(host)
        cache[host] = ip
        return ip
    except Exception:
        return None

def parse_node_to_xray_outbound(node_str):
    try:
        if node_str.startswith("vless://"):
            m = re.search(r"vless://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if not m:
                return None, None, None
            uuid_str, server, port_s, query = m.groups()
            port = int(port_s)
            params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
            
            # 过滤掉无法通过 GFW 的纯明文无证书节点
            if params.get("security") not in ["tls", "reality"]:
                return None, None, None

            outbound = {
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": server,
                        "port": port,
                        "users": [{"id": uuid_str, "encryption": params.get("encryption", "none")}]
                    }]
                },
                "streamSettings": {
                    "network": params.get("type", "tcp"),
                    "security": params.get("security")
                }
            }
            if params.get("security") == "reality":
                pbk = params.get("pbk", "")
                if not pbk:
                    return None, None, None
                outbound["streamSettings"]["realitySettings"] = {
                    "serverName": params.get("sni", server),
                    "publicKey": pbk,
                    "shortId": params.get("sid", ""),
                    "fingerprint": params.get("fp", "chrome")
                }
            elif params.get("security") == "tls":
                outbound["streamSettings"]["tlsSettings"] = {
                    "serverName": params.get("sni", server),
                    "allowInsecure": True
                }
            if params.get("type") == "ws":
                outbound["streamSettings"]["wsSettings"] = {
                    "path": urllib.parse.unquote(params.get("path", "/")),
                    "headers": {"Host": params.get("host", server)}
                }
            return outbound, server, port

        elif node_str.startswith("vmess://"):
            b64 = node_str[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            server = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            uuid_str = str(data.get("id", "")).strip()
            if not server or port <= 0:
                return None, None, None
            
            is_tls = data.get("tls") in ["tls", "1"]
            outbound = {
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": server,
                        "port": port,
                        "users": [{"id": uuid_str, "alterId": int(data.get("aid", 0)), "security": "auto"}]
                    }]
                },
                "streamSettings": {
                    "network": data.get("net", "tcp"),
                    "security": "tls" if is_tls else "none"
                }
            }
            if data.get("net") == "ws":
                outbound["streamSettings"]["wsSettings"] = {
                    "path": data.get("path", "/"),
                    "headers": {"Host": data.get("host", server)}
                }
            return outbound, server, port

        elif node_str.startswith("trojan://"):
            m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if not m:
                return None, None, None
            password, server, port_s, query = m.groups()
            port = int(port_s)
            params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
            
            outbound = {
                "protocol": "trojan",
                "settings": {
                    "servers": [{"address": server, "port": port, "password": password}]
                },
                "streamSettings": {
                    "network": params.get("type", "tcp"),
                    "security": "tls",
                    "tlsSettings": {"serverName": params.get("sni", server), "allowInsecure": True}
                }
            }
            return outbound, server, port
    except Exception:
        pass
    return None, None, None

def convert_to_clash_dict(node_str, name):
    try:
        outbound, server, port = parse_node_to_xray_outbound(node_str)
        if not outbound:
            return None
        proto = outbound["protocol"]
        if proto == "vless":
            user = outbound["settings"]["vnext"][0]["users"][0]
            stream = outbound["streamSettings"]
            proxy = {
                "name": name,
                "type": "vless",
                "server": server,
                "port": port,
                "uuid": user["id"],
                "udp": True,
                "tls": stream.get("security") in ["tls", "reality"],
                "skip-cert-verify": True
            }
            if stream.get("security") == "reality":
                r_set = stream.get("realitySettings", {})
                proxy["reality-opts"] = {"public-key": r_set.get("publicKey", "")}
                proxy["servername"] = r_set.get("serverName", server)
                proxy["client-fingerprint"] = r_set.get("fingerprint", "chrome")
            if stream.get("network") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = stream.get("wsSettings", {})
            return proxy
        elif proto == "vmess":
            user = outbound["settings"]["vnext"][0]["users"][0]
            stream = outbound["streamSettings"]
            proxy = {
                "name": name,
                "type": "vmess",
                "server": server,
                "port": port,
                "uuid": user["id"],
                "alterId": user.get("alterId", 0),
                "cipher": "auto",
                "udp": True,
                "tls": stream.get("security") == "tls",
                "skip-cert-verify": True
            }
            if stream.get("network") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = stream.get("wsSettings", {})
            return proxy
        elif proto == "trojan":
            srv = outbound["settings"]["servers"][0]
            stream = outbound["streamSettings"]
            return {
                "name": name,
                "type": "trojan",
                "server": server,
                "port": port,
                "password": srv["password"],
                "udp": True,
                "sni": stream.get("tlsSettings", {}).get("serverName", server),
                "skip-cert-verify": True
            }
    except Exception:
        pass
    return None

def test_single_node_xray(node_tuple):
    raw_node, server, port = node_tuple
    outbound, _, _ = parse_node_to_xray_outbound(raw_node)
    if not outbound:
        return None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        socks_port = s.getsockname()[1]

    task_id = uuid.uuid4().hex
    cfg_path = f"xray_tmp_{task_id}.json"

    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": False}
        }],
        "outbounds": [outbound]
    }
    
    with open(cfg_path, "w") as f:
        json.dump(config, f)

    proc = subprocess.Popen(["./xray", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.35)

    success = False
    delay_ms = 0
    start_t = time.time()
    try:
        proxies = {
            "http": f"socks5h://127.0.0.1:{socks_port}",
            "https": f"socks5h://127.0.0.1:{socks_port}"
        }
        # 严苛测活：真实拉取 HTTP 204，拒绝 TCP 假连接
        resp = requests.get("http://connectivitycheck.gstatic.com/generate_204", proxies=proxies, timeout=3.5)
        if resp.status_code == 204:
            delay_ms = int((time.time() - start_t) * 1000)
            if 50 < delay_ms < 2600:
                success = True
    except Exception:
        success = False
    finally:
        proc.kill()
        proc.wait()
        try:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)
        except Exception:
            pass

    if success:
        return (raw_node, server, port, delay_ms)
    return None

def run_real_delay_test_xray(candidates):
    print(f"[*] 启动 Xray 真实双向 HTTP 通道测活，物理独立候选节点: {len(candidates)}...")
    alive = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(test_single_node_xray, item): item for item in candidates}
        for future in as_completed(futures):
            res = future.result()
            if res:
                alive.append(res)
                if len(alive) % 20 == 0:
                    print(f"[+] 当前已核验可用节点: {len(alive)} 个")
    print(f"[+] 测活完成！真实可用节点总数: {len(alive)}")
    return alive

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

def classify_and_filter(alive_nodes):
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    def classify_item(item):
        raw_node, server, port, delay = item
        ip = resolve_host_cached(server)
        if not ip:
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

        # 严格家宽判定：必须匹配真实运营商 ASN
        is_residential = False
        try:
            a = asn_reader.get(ip)
            asn = a.get("autonomous_system_number", 0) if a else 0
            org = str(a.get("autonomous_system_organization", "")).lower() if a else ""
            
            if asn in REAL_RESIDENTIAL_ASNS:
                is_residential = True
            elif asn not in DATACENTER_ASNS:
                rdns = get_rdns_host(ip)
                if any(k in rdns for k in ["broadband", "dynamic", "pppoe", "cust", "hinet-ip"]):
                    is_residential = True
                elif any(k in org for k in ["broadband", "chunghwa", "consumer", "hinet"]):
                    is_residential = True
        except Exception:
            pass

        c_dict = convert_to_clash_dict(raw_node, "temp")
        if not c_dict:
            return None

        return {
            "link": raw_node,
            "clash_proxy": c_dict,
            "country": str(country_code).upper(),
            "is_residential": is_residential,
            "server_ip": ip,
            "port": port,
            "delay": delay
        }

    print("[*] 正在解析出口国家并鉴定住宅属性...")
    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(classify_item, item) for item in alive_nodes]
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
    formatted_links = []
    formatted_proxies = []
    
    # 局部物理排重，确保每个出库文件没有一个重复 IP:端口
    seen_local = set()
    cleaned = []
    for item in nodes_list:
        ep = f"{item['server_ip']}:{item['port']}"
        if ep not in seen_local:
            seen_local.add(ep)
            cleaned.append(item)

    for idx, item in enumerate(cleaned, start=1):
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
    else:
        for f in ["residential-clash.yaml", "residential-singbox.json"]:
            p = os.path.join(OUTPUT_DIR, f)
            if os.path.exists(p): os.remove(p)

    # 3. 按国家分类【非家宽】
    shutil.rmtree(COUNTRY_DIR, ignore_errors=True)
    os.makedirs(COUNTRY_DIR, exist_ok=True)
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
    shutil.rmtree(RESIDENTIAL_COUNTRY_DIR, ignore_errors=True)
    os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in res_by_cc.items():
        cr_links, cr_proxies = format_node_group(n_list, res_tag_force=True)
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(cr_links).encode()).decode())
        export_clash_yaml(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))
        export_singbox_json(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"singbox-{cc}.json"))

    print(f"[*] 导出完毕！全量真活: {len(all_links)} | 家宽真活: {len(res_links)}")
    return len(all_links), len(res_links)

def update_readme():
    repo_name = os.environ.get("GITHUB_REPOSITORY", "heleihub/Free-node-subscription").strip()
    # 动态时间戳，用来击碎 jsDelivr 的顽固死缓存
    cache_bust = int(time.time())
    
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
        # 带上 ?v={cache_bust}，客户端点击或拉取绝不会拿到旧缓存
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/{cc}.txt?v={cache_bust}"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/clash-{cc}.yaml?v={cache_bust}"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/singbox-{cc}.json?v={cache_bust}"
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
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/{cc}.txt?v={cache_bust}"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/clash-{cc}.yaml?v={cache_bust}"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/singbox-{cc}.json?v={cache_bust}"
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
> ⚡ **真实可用保障**: 所有节点由 `Xray-core` 建立实际代理隧道并完成真实 HTTP 传输握手，拒绝虚假通畅与死节点。无论是通过免翻 CDN 直链还是官方原生 Raw 直链拉取，节点命名格式完全一致。

---

## 📌 全部节点总订阅链接

| 客户端 / 格式类型 | 节点总数 | 免翻 CDN 订阅直链 (国内直连) | 官方原生 Raw 直链 (开启代理) |
| :--- | :---: | :--- | :--- |
| 🚀 **Clash (YAML 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/clash.yaml?v={cache_bust}` | `https://raw.githubusercontent.com/{repo_name}/main/output/clash.yaml` |
| ⚡ **V2RayN (Base64 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/v2ray.txt?v={cache_bust}` | `https://raw.githubusercontent.com/{repo_name}/main/output/v2ray.txt` |
| 📦 **sing-box (JSON 格式)** | `{total_count}` | `https://cdn.jsdelivr.net/gh/{repo_name}@main/output/singbox.json?v={cache_bust}` | `https://raw.githubusercontent.com/{repo_name}/main/output/singbox.json` |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 经 MaxMind ASN 数据库与运营商白名单探测，排除所有云主机/数据中心，保留真实民用宽带。

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
   - **Clash / Clash Verge / Mihomo Party**：直接复制上方表格中的 **Clash 专属订阅** 链接[cite: 4]。
   - **v2rayN / v2rayNG**：直接复制上方表格中的 **V2RayN 专属订阅** 链接[cite: 4]。
   - **sing-box**：直接使用上方 **sing-box 专属订阅** 链接[cite: 4]。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[+] README.md 实时动态表格更新完毕！真实总节点: {total_count}, 真实家宽: {res_count}")

if __name__ == "__main__":
    setup_environment()
    raw_nodes = fetch_raw_nodes()

    candidates = []
    seen_endpoints = set()

    print("[*] 正在执行底层物理 IP 强力去重...")
    for raw in raw_nodes:
        outbound, server, port = parse_node_to_xray_outbound(raw)
        if outbound and server and port:
            ip = resolve_host_cached(server)
            if ip:
                ep = f"{ip}:{port}"
                if ep not in seen_endpoints:
                    seen_endpoints.add(ep)
                    candidates.append((raw, server, port))

    print(f"[*] 物理 IP 去重完成，唯一候选节点数: {len(candidates)}")
    alive_nodes = run_real_delay_test_xray(candidates)
    verified = classify_and_filter(alive_nodes)
    export_subscriptions(verified)
    update_readme()
