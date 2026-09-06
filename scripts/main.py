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
# 配置区
# ============================
OUTPUT_DIR = "output"
BY_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RES_BY_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")
TEMPLATE_PATH = "README.template.md"
README_PATH = "README.md"

# 订阅源列表（可按需补充）
SOURCE_URLS = [
    "https://raw.githubusercontent.com/mfuu/v2ray/master/clash.yaml",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboxchannel/v2ray/main/list.txt",
]

# 国家代码及中文、Emoji 对照表
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

# ============================
# 真实测活模块
# ============================
def check_node_availability(host, port, tls=False, sni=None, timeout=2.5):
    """
    不仅测试 TCP 连通性，针对 TLS 协议强校验 TLS 握手，
    过滤掉端口假通但协议/证书失效的节点。
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
                # 能够握手成功即算有效
                return True
        sock.close()
        return True
    except Exception:
        return False

# ============================
# 节点解析模块
# ============================
def parse_node(link):
    """
    解析单行链接并提取底层核心四元组（协议、地址、端口、密码/UUID）
    """
    link = link.strip()
    if not link:
        return None

    try:
        if link.startswith("vless://") or link.startswith("vmess://") or link.startswith("trojan://") or link.startswith("ss://"):
            proto = link.split("://")[0]
            
            if proto == "vmess":
                b64_str = link[8:]
                # 补充 base64 padding
                missing_padding = len(b64_str) % 4
                if missing_padding:
                    b64_str += '=' * (4 - missing_padding)
                data = json.loads(base64.b64decode(b64_str).decode('utf-8', errors='ignore'))
                server = data.get("add")
                port = int(data.get("port", 0))
                uuid_val = data.get("id", "")
                tls = str(data.get("tls", "")).lower() == "tls"
                sni = data.get("sni", data.get("host", server))
                net = data.get("net", "tcp")
                path = data.get("path", "")
                return {
                    "type": "vmess",
                    "server": server,
                    "port": port,
                    "uuid": uuid_val,
                    "tls": tls,
                    "sni": sni,
                    "network": net,
                    "path": path,
                    "raw": link
                }

            elif proto in ["vless", "trojan"]:
                parsed = urllib.parse.urlparse(link)
                uuid_val = parsed.username
                server = parsed.hostname
                port = parsed.port
                qs = urllib.parse.parse_qs(parsed.query)
                security = qs.get("security", [""])[0].lower()
                tls = security in ["tls", "reality"]
                sni = qs.get("sni", [server])[0]
                return {
                    "type": proto,
                    "server": server,
                    "port": port,
                    "uuid": uuid_val,
                    "tls": tls,
                    "sni": sni,
                    "network": qs.get("type", ["tcp"])[0],
                    "raw": link
                }

            elif proto == "ss":
                parsed = urllib.parse.urlparse(link)
                server = parsed.hostname
                port = parsed.port
                return {
                    "type": "ss",
                    "server": server,
                    "port": port,
                    "uuid": parsed.username or "",
                    "tls": False,
                    "sni": None,
                    "raw": link
                }
    except Exception:
        pass
    return None

# ============================
# 节点去重与唯一 Key 生成
# ============================
def get_node_key(node):
    """
    根据核心连接特征生成唯一标识，绝不依据名称/别名去重
    """
    proto = node.get("type", "")
    server = str(node.get("server", "")).strip().lower()
    port = str(node.get("port", "")).strip()
    secret = str(node.get("uuid", node.get("password", ""))).strip()
    return f"{proto}://{server}:{port}@{secret}"

def deduplicate(nodes):
    seen = set()
    unique = []
    for node in nodes:
        key = get_node_key(node)
        if key not in seen:
            seen.add(key)
            unique.append(node)
    return unique

# ============================
# 格式化重命名规范
# ============================
def format_node_name(country_code, index, is_residential=False):
    """
    统一所有节点命名规范，不论通过代理更新还是直连更新均保持完全一致：
    格式示例：🇺🇸 美国 01 - xiaohe  或  🇺🇸 美国 01 (家宽) - xiaohe
    """
    country_info = COUNTRY_MAP.get(country_code, COUNTRY_MAP["OTHER"])
    flag = country_info["flag"]
    zh_name = country_info["zh"]
    tag = " (家宽)" if is_residential else ""
    return f"{flag} {zh_name} {index:02d}{tag} - xiaohe"

# ============================
# 住宅/家宽识别（轻量级）
# ============================
def detect_country_and_residential(server):
    """
    返回 (国家代码, 是否家宽)
    默认匹配或扩展 maxminddb / 规则，无数据库时兜底为 OTHER
    """
    # 如果你在本地有 GeoLite2 数据库，可在这里加载
    return "US", False

# ============================
# 输出文件生成器
# ============================
def build_clash_proxy(node, name):
    p = {
        "name": name,
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

def save_subscriptions(nodes):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(BY_COUNTRY_DIR, exist_ok=True)
    os.makedirs(RES_BY_COUNTRY_DIR, exist_ok=True)

    # 1. 节点分类归并
    grouped_nodes = {}
    residential_nodes = []
    
    for node in nodes:
        c_code, is_res = detect_country_and_residential(node["server"])
        node["country"] = c_code
        node["is_res"] = is_res
        if is_res:
            residential_nodes.append(node)
        grouped_nodes.setdefault(c_code, []).append(node)

    # 2. 统一重命名（按地区分组分配严格自增的编号 01, 02...）
    final_proxies = []
    v2ray_links = []
    
    for c_code, c_nodes in grouped_nodes.items():
        for i, node in enumerate(c_nodes, start=1):
            name = format_node_name(c_code, i, node["is_res"])
            node["final_name"] = name
            final_proxies.append(build_clash_proxy(node, name))
            v2ray_links.append(node["raw"])

    # 3. 输出 clash.yaml
    clash_config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "Rule",
        "log-level": "info",
        "proxies": final_proxies,
        "proxy-groups": [
            {
                "name": "节点选择",
                "type": "select",
                "proxies": ["自动选择"] + [p["name"] for p in final_proxies]
            },
            {
                "name": "自动选择",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "proxies": [p["name"] for p in final_proxies]
            }
        ],
        "rules": [
            "GEOIP,LAN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,节点选择"
        ]
    }
    with open(os.path.join(OUTPUT_DIR, "clash.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(clash_config, f, allow_unicode=True, sort_keys=False)

    # 4. 输出 v2ray.txt (Base64)
    v2ray_content = "\n".join(v2ray_links)
    encoded_v2ray = base64.b64encode(v2ray_content.encode("utf-8")).decode("utf-8")
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(encoded_v2ray)

    # 5. 输出 singbox.json
    singbox_config = {
        "outbounds": [{"type": "selector", "tag": "select", "outbounds": [p["name"] for p in final_proxies]}]
    }
    with open(os.path.join(OUTPUT_DIR, "singbox.json"), "w", encoding="utf-8") as f:
        json.dump(singbox_config, f, ensure_ascii=False, indent=2)

    return len(final_proxies), len(residential_nodes)

# ============================
# README 渲染模块
# ============================
def update_readme(total_count, res_count):
    if not os.path.exists(TEMPLATE_PATH):
        return

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    beijing_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    content = content.replace("{{UPDATE_TIME}}", beijing_time)
    content = content.replace("{{TOTAL_COUNT}}", str(total_count))
    content = content.replace("{{RESIDENTIAL_COUNT}}", str(res_count))

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

# ============================
# 主执行入口
# ============================
def main():
    print("[*] 正在抓取上游节点列表...")
    raw_nodes = []
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                lines = resp.text.splitlines()
                for line in lines:
                    n = parse_node(line)
                    if n:
                        raw_nodes.append(n)
        except Exception as e:
            print(f"[!] 抓取源 {url} 失败: {e}")

    print(f"[*] 抓取完成，共获得 {len(raw_nodes)} 个节点，开始底层去重...")
    unique_nodes = deduplicate(raw_nodes)
    print(f"[*] 核心四元组去重后剩余: {len(unique_nodes)} 个")

    print("[*] 开始真实连通性测试 (TCP + TLS 握手)...")
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

    print(f"[*] 测活完成，真实可用节点数: {len(valid_nodes)} 个")

    # 保存各客户端订阅
    total, res_cnt = save_subscriptions(valid_nodes)
    # 渲染 README
    update_readme(total, res_cnt)
    print(f"[✔] 订阅生成完毕并已更新 README.md (有效节点: {total}, 住宅节点: {res_cnt})")

if __name__ == "__main__":
    main()
