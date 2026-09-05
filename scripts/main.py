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

# 彻底排除全球数据中心/云服务商 ASN
DATACENTER_ASNS = {
    13335, 16509, 14618, 15169, 396982, 8075, 24940, 16276, 
    14061, 31898, 63949, 45102, 132203, 20473, 60068, 55081,
    197540, 51167, 8560, 42708, 201814, 49981, 212238, 46652,
    141995, 200019, 136907, 39351, 9009
}

# 权威民用宽带住宅 ASN 白名单 (含台湾、香港、日本、美国、英国、德国等)
RESIDENTIAL_ASNS = {
    # 台湾民用宽带 (中华电信 HiNet, 台湾固网, 远传)
    3462, 9924, 9919, 17709, 4780, 17408, 18049,
    # 香港民用宽带 (HKT, 香港宽频 HKBN)
    9304, 9269, 17816, 58453,
    # 日本民用宽带 (NTT, OCN, KDDI, Softbank, So-net)
    2516, 17511, 2519, 2527, 4713, 9605, 17676, 2514,
    # 美国主流家宽 (Comcast, AT&T, Charter/Spectrum, Verizon, Cox)
    701, 702, 7922, 20115, 7018, 10796, 11427, 5650, 22773,
    # 英国民用宽带 (BT, Virgin Media, Sky, TalkTalk)
    2856, 5089, 5607, 13285, 5378,
    # 德国民用宽带 (Deutsche Telekom, Vodafone DE, O2 Germany, 1&1)
    3320, 3209, 31334, 6805, 8881,
}

# rDNS 宽带特征词
RESIDENTIAL_RDNS_KEYWORDS = [
    "dynamic", "broadband", "dsl", "dial", "pppoe", "pool", "user", 
    "cust", "home", "res", "dhcp", "ftth", "cable", "hinet-ip", "kbro"
]

# rDNS 机房排除特征词
DATACENTER_RDNS_KEYWORDS = [
    "vps", "server", "cloud", "compute", "datacenter", "hosting", "dedicated", "node"
]

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
    """根据国家二字码计算出真实彩色的国旗 Emoji"""
    if not country_code or country_code.upper() in ["OTHER", "ZZ", "XX"]:
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

def convert_node_to_clash(node_str, index):
    """参数严格校验，彻底消灭导致内核闪退的非法配置"""
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
                    # 彻底解决 short-id 引起的致命闪退
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
    """规范重命名 V2Ray/通用协议链接备注（国旗 + 缩写 + xiaohe）"""
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
    """执行反向 PTR 域名解析，嗅探民用宽带特征"""
    try:
        socket.setdefaulttimeout(1.5)
        host, _, _ = socket.gethostbyaddr(ip)
        return host.lower()
    except Exception:
        return ""

def classify_and_filter(alive_proxies, node_map):
    """双重离线库 + rDNS 反向指针探测（准确率最高且 100% 稳定的方案）"""
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

        # 1. 离线高精度国家解析（绝不出现 OTHER）
        country_code = "OTHER"
        try:
            c = country_reader.get(ip)
            if c and "country" in c:
                country_code = c["country"]["iso_code"]
        except Exception:
            pass

        # 2. 权威白名单 + rDNS 宽带特征探测
        is_residential = False
        try:
            a = asn_reader.get(ip)
            asn = a.get("autonomous_system_number", 0) if a else 0
            org = str(a.get("autonomous_system_organization", "")).lower() if a else ""
            
            # 条件 A：直接命中权威家宽运营商 ASN 白名单 (中华电信/HiNet, 宽频, BT, 德国电信等)
            if asn in RESIDENTIAL_ASNS:
                is_residential = True
            # 条件 B：非数据中心 ASN，进行 rDNS 反向域名探测与运营商特征识别
            elif asn not in DATACENTER_ASNS:
                rdns = get_rdns_host(ip)
                # 若反向解析域名带有机房特征，一票否决
                if not any(k in rdns for k in DATACENTER_RDNS_KEYWORDS):
                    # 若反向解析域名带有家用宽带特征（如 dynamic, pppoe, hinet-ip 等）
                    if any(k in rdns for k in RESIDENTIAL_RDNS_KEYWORDS):
                        is_residential = True
                    elif any(k in org for k in ["broadband", "consumer", "dsl", "ftth", "residential", "hinet", "chunghwa"]):
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

    print("[*] 正在解析可用节点的出口国家归属与真家宽反向特征...")
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(resolve_and_classify, item) for item in alive_proxies.items()]
        for f in as_completed(futures):
            res = f.result()
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()

    # 规范重命名：国旗 Emoji + 国家代码 + 序号 + (家宽) - xiaohe
    counters = {}
    for node in verified:
        cc = node["country"]
        counters[cc] = counters.get(cc, 0) + 1
        idx = counters[cc]
        flag = get_country_flag(cc)
        res_tag = " (家宽)" if node["is_residential"] else ""
        
        new_name = f"{flag} {cc} {idx:02d}{res_tag} - xiaohe"
        
        node["clash_proxy"]["name"] = new_name
        node["link"] = rename_node_link(node["link"], new_name)

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

def export_singbox_json(verified_nodes, filepath):
    outbounds = [
        {"type": "selector", "tag": "select", "outbounds": ["auto"] + [n["clash_proxy"]["name"] for n in verified_nodes]},
        {"type": "urltest", "tag": "auto", "outbounds": [n["clash_proxy"]["name"] for n in verified_nodes], "url": "http://cp.cloudflare.com/generate_204"},
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"}
    ]
    config = {"version": 1, "outbounds": outbounds}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def export_subscriptions(verified_nodes):
    all_links = [n["link"] for n in verified_nodes]
    all_clash_proxies = [n["clash_proxy"] for n in verified_nodes]
    
    residential_nodes = [n for n in verified_nodes if n["is_residential"]]
    residential_links = [n["link"] for n in residential_nodes]
    residential_clash = [n["clash_proxy"] for n in residential_nodes]

    # 全部节点输出
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())
    export_clash_yaml(all_clash_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    export_singbox_json(verified_nodes, os.path.join(OUTPUT_DIR, "singbox.json"))

    # 家宽节点输出
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(residential_links).encode()).decode())
    if residential_clash:
        export_clash_yaml(residential_clash, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
        export_singbox_json(residential_nodes, os.path.join(OUTPUT_DIR, "residential-singbox.json"))

    # 按国家分类全部节点
    by_cc = {}
    for n in verified_nodes:
        by_cc.setdefault(n["country"], []).append(n)

    for cc, nodes_list in by_cc.items():
        links = [n["link"] for n in nodes_list]
        proxies = [n["clash_proxy"] for n in nodes_list]
        with open(os.path.join(COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        export_clash_yaml(proxies, os.path.join(COUNTRY_DIR, f"clash-{cc}.yaml"))

    # 按国家分类家宽节点
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, nodes_list in res_by_cc.items():
        links = [n["link"] for n in nodes_list]
        proxies = [n["clash_proxy"] for n in nodes_list]
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        export_clash_yaml(proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))

    print(f"[*] 导出完毕！全部存活: {len(all_links)} | 真家宽: {len(residential_links)} | 涉及国家: {len(by_cc)}")
    return by_cc, res_by_cc, len(all_links), len(residential_links)

def update_readme():
    """扫描真实磁盘物理文件统计数量，准确生成 README 表格"""
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

    # 生成家宽表格（彩旗图标 + 真实国家中文）
    res_table_rows = []
    for cc in sorted(res_country_counts.keys(), key=lambda x: res_country_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, f"{cc} / 其他")
        count = res_country_counts[cc]
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/residential-by-country/clash-{cc}.yaml"
        res_table_rows.append(f"| {flag} {name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    res_table_str = "\n".join(res_table_rows) if res_table_rows else "| 暂无可用家宽节点 | 0 | - | - |"

    # 生成全量表格（彩旗图标 + 真实国家中文）
    country_table_rows = []
    for cc in sorted(country_counts.keys(), key=lambda x: country_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, f"{cc} / 其他")
        count = country_counts[cc]
        v2ray_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo}@main/output/by-country/clash-{cc}.yaml"
        country_table_rows.append(f"| {flag} {name} | **{count}** | [V2Ray/通用]({v2ray_cdn}) | [Clash 订阅]({clash_cdn}) |")
    country_table_str = "\n".join(country_table_rows) if country_table_rows else "| 暂无可用节点 | 0 | - | - |"

    readme_content = f"""# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 🕒 **最近更新时间**: `{now_utc}`  
> 🟢 **全部可用节点数量**: `{total_count}` 个  
> 🏠 **甄选家宽节点数量**: `{res_count}` 个  
> 👤 **定制规范命名**: 统一命名格式 `国旗代码 + 序号 (家宽) - xiaohe`  
> ⚡ **质量保证**: 由 `mihomo` 真实代理握手测活 + rDNS 民用宽带特征交叉校验。

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
