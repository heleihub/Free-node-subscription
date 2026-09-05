# 🚀 自动聚合与测活订阅节点项目 (含家宽/住宅IP分类)

本仓库基于 GitHub Actions 定时自动抓取公共多源节点，执行真连接连通性测活，并依据 MaxMind GeoIP 与 ASN 数据库完成国家分类与家宽节点识别。

## 📌 订阅地址列表 (将链接中的用户名和仓库名替换为您自己的)

### 1. 🏠 家宽 / 住宅 IP 专区
> 经 ASN 数据库过滤剔除云机房商（AWS/Azure/GCP/Cloudflare/Hetzner 等）后的民用宽带节点：
- **Base64 订阅**：
  `https://raw.githubusercontent.com/你的用户名/你的仓库名/main/output/residential.txt`
- **CDN 加速链接**：
  `https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/residential.txt`

---

### 2. 🌐 全量有效节点订阅
- **Base64 订阅**：
  `https://raw.githubusercontent.com/你的用户名/你的仓库名/main/output/v2ray.txt`
- **CDN 加速链接**：
  `https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/v2ray.txt`

---

### 3. 🗺️ 按国家分类订阅
位于 `output/by-country/` 目录中（格式为两字母国家代码，例如 `HK.txt`, `JP.txt`, `US.txt`, `SG.txt` 等）：
- **香港 (HK)**：`https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/by-country/HK.txt`
- **日本 (JP)**：`https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/by-country/JP.txt`
- **美国 (US)**：`https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/by-country/US.txt`
- **新加坡 (SG)**：`https://cdn.jsdelivr.net/gh/你的用户名/你的仓库名@main/output/by-country/SG.txt`

---

## ⚙️ 部署使用方法

1. 将本仓库代码上传至你的 GitHub。
2. 开启 Actions 写入权限：
   - 仓库 **Settings** -> **Actions** -> **General**。
   - 找到 **Workflow permissions**，勾选 **Read and write permissions** 并保存。
3. 进入 **Actions** 页面，找到 `Update Subscriptions`，点击 **Run workflow** 即可立刻手动触发一次自动化采集与测活。
