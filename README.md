# 🚀 自动测活与多源免费节点订阅池 (含真家宽/住宅IP分类)

> 🕒 **最后更新时间**: `2026-09-05 16:38:41 UTC`  
> 🟢 **真连接可用节点总量**: `7` 个  
> 🏠 **甄选住宅/家宽节点总量**: `6` 个  
> ⚡ **质量保证**: 所有节点均由 `mihomo` (Clash Meta) 内核执行真实代理握手（Google 204）测活过滤，拒绝虚假通畅与死节点。

---

## 📌 核心订阅总链接

| 分类类型 | 可用数量 | GitHub 原始订阅链接 | CDN 快速订阅链接 (免翻推荐) |
| :--- | :---: | :--- | :--- |
| 🌐 **全部有效节点总汇** | `7` | [Raw Link](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/v2ray.txt) | `https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/v2ray.txt` |
| 🏠 **全量住宅家宽总汇** | `6` | [Raw Link](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential.txt) | `https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential.txt` |

---

## 🏠 住宅家宽节点 (按国家/地区分类)
> 经 MaxMind ASN 数据库精准排除所有云端机房/服务器节点，保留真实居民宽带 IP。

| 代码 | 国家/地区 | 家宽节点数 | Raw 链接 | 免翻 CDN 订阅链接 |
| :---: | :--- | :---: | :---: | :--- |
| 🇬🇧 GB | 英国 / United Kingdom | **2** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential-by-country/GB.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential-by-country/GB.txt) |
| 🇳🇱 NL | 荷兰 / Netherlands | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential-by-country/NL.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential-by-country/NL.txt) |
| 🌐 SC | SC / Other | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential-by-country/SC.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential-by-country/SC.txt) |
| 🇩🇪 DE | 德国 / Germany | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential-by-country/DE.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential-by-country/DE.txt) |
| 🇷🇺 RU | 俄罗斯 / Russia | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/residential-by-country/RU.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/residential-by-country/RU.txt) |

---

## 🗺️ 全量节点分流 (按国家/地区分类)

| 代码 | 国家/地区 | 可用节点数 | Raw 链接 | 免翻 CDN 订阅链接 |
| :---: | :--- | :---: | :---: | :--- |
| 🇬🇧 GB | 英国 / United Kingdom | **2** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/GB.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/GB.txt) |
| 🌐 OTHER | 其他地区 / Other | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/OTHER.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/OTHER.txt) |
| 🇳🇱 NL | 荷兰 / Netherlands | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/NL.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/NL.txt) |
| 🌐 SC | SC / Other | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/SC.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/SC.txt) |
| 🇩🇪 DE | 德国 / Germany | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/DE.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/DE.txt) |
| 🇷🇺 RU | 俄罗斯 / Russia | **1** | [查看 Raw](https://raw.githubusercontent.com/heleihub/Free-node-subscription/main/output/by-country/RU.txt) | [CDN 订阅](https://cdn.jsdelivr.net/gh/heleihub/Free-node-subscription@main/output/by-country/RU.txt) |

---

## 🛠️ 项目特性与说明

1. **真连接连通检测**：摒弃单纯的 TCP 端口 ping，使用 mihomo 内核通过代理链路实际访问 Google 204 端点并校验往返时间（RTT $\le$ 3000ms），测出可用即代表真实可用。
2. **多源采集聚合**：集成 GitHub 活跃订阅池，并自动爬取 `outlinekeys.com` 及 `shadowmere.xyz` 的节点。
3. **全自动维护**：通过 GitHub Actions 全自动构建，运行后自动重绘本页面的节点统计与各分流文件。
