#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import base64
import socket
import ssl
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import yaml

# ============================
# 基础路径定义
# ============================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
BY_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RES_BY_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")
TEMPLATE_PATH = os.path.join(BASE_DIR, "README.template.md")
README_PATH = os.path.join(BASE_DIR, "README.md")

# 订阅源列表（包含 Clash 与 Base64 混合源）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/mfuu/v2ray/master/clash.yaml",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboxchannel/v2ray/main/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/ssrsub/ssr/master/v2ray",
]

# 国家与国旗对应字典
COUNTRY_MAP = {
    "HK": {"zh": "香港", "flag": "🇭🇰"},
    "TW": {"zh": "台湾", "flag": "🇹🇼"},
    "JP": {"zh": "日本", "flag": "🇯🇵"},
    "KR": {"zh": "韩国", "flag": "🇰🇷"},
    "SG": {"zh": "新加坡", "flag": "🇸🇬"},
    "US": {"zh": "美国", "flag": "🇺🇸"},
    "GB": {"zh": "英国", "flag": "🇬🇧"},
    "DE": {"zh": "德国", "flag": "🇩🇪"},
    "FR": {"zh": "法国", "flag": "🇫🇷"},
    "CA": {"zh": "加拿大", "flag": "🇨🇦"},
    "AU": {"zh": "澳大利亚", "flag": "🇦🇺"},
    "OTHER": {"zh": "其他", "flag": "🌐"}
}

# 常见国家识别正则
REGEX_COUNTRY = {
    "HK": re.compile(r"香港|HK|Hong Kong|🇭🇰", re.I),
    "TW": re.compile(r"台湾|TW|Taiwan|🇹🇼", re.I),
    "JP": re.compile(r"日本|JP|Japan|🇯🇵", re.I),
    "KR": re.compile(r"韩国|KR|Korea|🇰🇷", re.I),
    "SG": re.compile(r"新加坡|SG|Singapore|🇸🇬", re.I),
    "US": re.compile(r"美国|US|United States|家宽|🇺🇸", re.I),
    "GB": re.compile(r"英国|GB|UK|United Kingdom|🇬🇧", re.I),
    "DE": re.compile(r"德国|DE|Germany|🇩🇪", re.I),
    "FR": re.compile(r"法国|FR|France|🇫🇷", re.I),
    "CA": re.compile(r"加拿大|CA|Canada|🇨🇦", re.I),
    "AU": re.compile(r"澳大利亚|AU|Australia|🇦🇺", re.I),
}

# ============================
# 真实测活模块（TLS + TCP 握手验证）
# ============================
def check_node_availability(host, port, tls=False, sni=None, timeout=2.0):
    """
    建立 TCP 连接，并针对 TLS 协议强行校验握手，过滤虚假开放端口
    """
    try:
        port = int(port)
        sock = socket.create_connection((host, port), timeout=timeout)
        if tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            server_name = sni if sni else host
            with context.wrap_socket(sock, server_hostname=server_name) as ssock:
                ssock.settimeout(timeout)
                return True
        sock.close()
        return True
    except Exception:
        return False

# ============================
# 节点解析与提取
# ============================
def parse_single_link(link):
    link = link.strip()
    if not link:
        return None

    try:
        if link.startswith("vmess://"):
            b64_str = link[8:]
            b64_str += '=' * ((4 - len(b64_str) % 4) % 4)
            data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
            server = data.get("add")
            port = int(data.get("port", 0))
            if not server or not port:
                return None
            return {
                "type": "vmess",
                "server": server,
                "port": port,
                "uuid": data.get("id", ""),
                "tls": str(data.get("tls", "")).lower() == "tls",
                "sni": data.get("sni", data.get("host", server)),
                "network": data.get("net", "tcp"),
                "path": data.get("path", ""),
                "raw": link,
                "orig_name": data.get("ps", "")
            }

        elif link.startswith("vless://") or link.startswith("trojan://"):
            proto = link.split("://")[0]
            parsed = urllib.parse.urlparse(link)
            uuid_val = parsed.username
            server = parsed.hostname
            port = parsed.port
            if not server or not port:
                return None
            qs = urllib.parse.parse_qs(parsed.query)
            security = qs.get("security", [""])[0].lower()
            tls = security in ["tls", "reality"]
            sni = qs.get("sni", [server])[0]
            return {
                "type": proto,
                "server": server,
                "port": port,
                "uuid": uuid_val or "",
                "tls": tls,
                "sni": sni,
                "network": qs.get("type", ["tcp"])[0],
                "raw": link,
                "orig_name": urllib.parse.unquote(parsed.fragment or "")
            }

        elif link.startswith("ss://"):
            parsed = urllib.parse.urlparse(link)
            server = parsed.hostname
            port = parsed.port
            if not server or not port:
                return None
            return {
                "type": "ss",
                "server": server,
                "port": port,
                "uuid": parsed.username or "",
                "tls": False,
                "sni": None,
                "network": "tcp",
                "raw": link,
                "orig_name": urllib.parse.unquote(parsed.fragment or "")
            }
    except Exception:
        pass
    return None

def fetch_and_parse_all():
    all_nodes = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for url in SOURCE_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                continue
            text = r.text.strip()

            # 尝试作为 Clash YAML 解析
            if "proxies:" in text:
                try:
                    data = yaml.safe_load(text)
                    for p in data.get("proxies", []):
                        ptype = p.get("type")
                        if ptype in ["vmess", "vless", "trojan", "ss"]:
                            node = {
                                "type": ptype,
                                "server": p.get("server"),
                                "port": int(p.get("port", 0)),
                                "uuid": p.get("uuid", p.get("password", "")),
                                "tls": p.get("tls", False),
                                "sni": p.get("servername", p.get("sni", p.get("server"))),
                                "network": p.get("network", "tcp"),
                                "orig_name": p.get("name", "")
                            }
                            # 重构原始 link 备用
                            if node["type"] == "vless":
                                node["raw"] = f"vless://{node['uuid']}@{node['server']}:{node['port']}?security={'tls' if node['tls'] else 'none'}#{urllib.parse.quote(node['orig_name'])}"
                            elif node["type"] == "trojan":
                                node["raw"] = f"trojan://{node['uuid']}@{node['server']}:{node['port']}#{urllib.parse.quote(node['orig_name'])}"
                            else:
                                node["raw"] = ""
                            if node["server"] and node["port"]:
                                all_nodes.append(node)
                    continue
                except Exception:
                    pass

            # 尝试作为 Base64 解码
            decoded_text = text
            try:
                b64 = text + '=' * ((4 - len(text) % 4) % 4)
                decoded_text = base64.b64decode(b64).decode('utf-8', errors='ignore')
            except Exception:
                decoded_text = text

            for line in decoded_text.splitlines():
                n = parse_single_link(line)
                if n:
                    all_nodes.append(n)

        except Exception as e:
            print(f"[!] 抓取源失败 {url}: {e}")

    return all_nodes

# ============================
# 严格底层去重模块
# ============================
def deduplicate_nodes(nodes):
    """
    根据 协议 + 服务器IP/域名 + 端口 + 认证信息 严格去重
    彻底杜绝因别名自增编号导致的未去重问题
    """
    seen = set()
    unique = []
    for n in nodes:
        key = f"{n['type']}://{n['server'].lower().strip()}:{n['port']}@{str(n.get('uuid', '')).strip()}"
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return unique

# ============================
# 国家与家宽属性判断
# ============================
def identify_country_and_isp(node):
    text_to_search = f"{node.get('orig_name', '')} {node.get('sni', '')} {node.get('server', '')}"
    
    # 1. 判定国家
    matched_country = "OTHER"
    for c_code, reg in REGEX_COUNTRY.items():
        if reg.search(text_to_search):
            matched_country = c_code
            break
    
    # 2. 判定家宽 / 住宅节点
    is_res = False
    if re.search(r"家宽|住宅|Residential|ISP|Home", text_to_search, re.I):
        is_res = True

    return matched_country, is_res

# ============================
# 统一名称格式生成
# ============================
def format_node_name(country_code, index, is_res=False):
    """
    统一格式：{国旗} {国家中文} {序号:02d}{家宽标记} - xiaohe
    示例：🇺🇸 美国 01 (家宽) - xiaohe 或 🇭🇰 香港 02 - xiaohe
    """
    info = COUNTRY_MAP.get(country_code, COUNTRY_MAP["OTHER"])
    tag = " (家宽)" if is_res else ""
    return f"{info['flag']} {info['zh']} {index:02d}{tag} - xiaohe"

# ============================
# 配置构建辅助函数
# ============================
def build_clash_proxy(node):
    p = {
        "name": node["final_name"],
        "type": node["type"],
        "server": node["server"],
        "port": node["port"]
    }
    if node["type"] in ["vless", "vmess"]:
        p["uuid"] = node["uuid"]
        p["alterId"] = 0
        p["cipher"] = "auto"
        p["udp"] = True
        p["tls"] = node.get("tls", False)
        if node.get("sni"):
            p["servername"] = node["sni"]
        if node.get("network"):
            p["network"] = node["network"]
    elif node["type"] == "trojan":
        p["password"] = node["uuid"]
        p["udp"] = True
        p["sni"] = node.get("sni", node["server"])
    return p

def dump_clash(proxies, filepath):
    names = [p["name"] for p in proxies]
    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "Rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "节点选择", "type": "select", "proxies": ["自动选择"] + names},
            {"name": "自动选择", "type": "url-test", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": names}
        ],
        "rules": ["GEOIP,LAN,DIRECT", "GEOIP,CN,DIRECT", "MATCH,节点选择"]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def dump_singbox(proxies, filepath):
    tags = [p["name"] for p in proxies]
    config = {
        "outbounds": [
            {"type": "selector", "tag": "select", "outbounds": ["urltest"] + tags},
            {"type": "urltest", "tag": "urltest", "outbounds": tags, "url": "http://cp.cloudflare.com/generate_204"}
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def dump_txt_b64(nodes, filepath):
    links = [n["raw"] for n in nodes if n.get("raw")]
    content = "\n".join(links)
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(b64)

# ============================
# 保存全部分类文件
# ============================
def save_all_outputs(nodes):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(BY_COUNTRY_DIR, exist_ok=True)
    os.makedirs(RES_BY_COUNTRY_DIR, exist_ok=True)

    # 1. 归组分类
    country_groups = {}
    res_country_groups = {}
    all_res_nodes = []

    for n in nodes:
        c_code, is_res = identify_country_and_isp(n)
        n["country"] = c_code
        n["is_res"] = is_res
        country_groups.setdefault(c_code, []).append(n)
        if is_res:
            res_country_groups.setdefault(c_code, []).append(n)
            all_res_nodes.append(n)

    # 2. 统一重命名（按各国家组内顺序生成 01, 02 规范名称）
    all_clash_proxies = []
    for c_code, c_nodes in country_groups.items():
        for idx, n in enumerate(c_nodes, start=1):
            n["final_name"] = format_node_name(c_code, idx, n["is_res"])
            all_clash_proxies.append(build_clash_proxy(n))

    # 3. 输出全聚合文件
    dump_clash(all_clash_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    dump_singbox(all_clash_proxies, os.path.join(OUTPUT_DIR, "singbox.json"))
    dump_txt_b64(nodes, os.path.join(OUTPUT_DIR, "v2ray.txt"))

    # 4. 输出全家宽聚合文件
    res_clash_proxies = [build_clash_proxy(n) for n in all_res_nodes]
    dump_clash(res_clash_proxies, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
    dump_singbox(res_clash_proxies, os.path.join(OUTPUT_DIR, "residential-singbox.json"))
    dump_txt_b64(all_res_nodes, os.path.join(OUTPUT_DIR, "residential.txt"))

    # 5. 输出 output/by-country/ 下的各个国家文件
    for c_code, c_nodes in country_groups.items():
        c_proxies = [build_clash_proxy(n) for n in c_nodes]
        dump_txt_b64(c_nodes, os.path.join(BY_COUNTRY_DIR, f"{c_code}.txt"))
        dump_clash(c_proxies, os.path.join(BY_COUNTRY_DIR, f"clash-{c_code}.yaml"))
        dump_singbox(c_proxies, os.path.join(BY_COUNTRY_DIR, f"singbox-c_{c_code}.json"))

    # 6. 输出 output/residential-by-country/ 下的各个家宽国家文件
    for c_code, c_nodes in res_country_groups.items():
        c_proxies = [build_clash_proxy(n) for n in c_nodes]
        dump_txt_b64(c_nodes, os.path.join(RES_BY_COUNTRY_DIR, f"{c_code}.txt"))
        dump_clash(c_proxies, os.path.join(RES_BY_COUNTRY_DIR, f"clash-{c_code}.yaml"))
        dump_singbox(c_proxies, os.path.join(RES_BY_COUNTRY_DIR, f"singbox-{c_code}.json"))

    return len(nodes), len(all_res_nodes)

# ============================
# README 更新模块
# ============================
def update_readme(total_count, res_count):
    if not os.path.exists(TEMPLATE_PATH):
        return
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()

    beijing_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    rendered = tpl.replace("{{UPDATE_TIME}}", beijing_time)
    rendered = rendered.replace("{{TOTAL_COUNT}}", str(total_count))
    rendered = rendered.replace("{{RESIDENTIAL_COUNT}}", str(res_count))

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)

# ============================
# 主执行入口
# ============================
def main():
    print("[*] 正在抓取上游节点列表...")
    raw_nodes = fetch_and_parse_all()
    print(f"[*] 抓取完成，共获得 {len(raw_nodes)} 个节点")

    # 安全检查：若未抓取到节点，不覆盖原有数据，直接退出
    if not raw_nodes:
        print("[!] 抓取到的有效节点为 0，为防止误删现有仓库文件，停止更新并保留现状。")
        return

    print("[*] 开始底层连接参数严格去重...")
    unique_nodes = deduplicate_nodes(raw_nodes)
    print(f"[*] 去重后剩余节点数: {len(unique_nodes)}")

    print("[*] 开始并发测活 (TCP 连通性 + TLS 握手)...")
    valid_nodes = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        future_map = {
            executor.submit(
                check_node_availability,
                node["server"],
                node["port"],
                node.get("tls", False),
                node.get("sni")
            ): node
            for node in unique_nodes
        }
        for future in as_completed(future_map):
            node = future_map[future]
            if future.result():
                valid_nodes.append(node)

    print(f"[*] 测活完成，真实可用节点: {len(valid_nodes)}")
    if not valid_nodes:
        print("[!] 经测活后无存活节点，保留原有订阅文件不变。")
        return

    print("[*] 正在分类并生成全部国家与家宽配置文件...")
    total, res_cnt = save_all_outputs(valid_nodes)
    update_readme(total, res_cnt)
    print(f"[✔] 全部分类订阅更新完成！有效节点: {total}，家宽节点: {res_cnt}")

if __name__ == "__main__":
    main()
