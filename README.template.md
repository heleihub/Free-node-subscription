# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 🕒 **最近更新时间**: `{NOW_UTC}`  
> 🟢 **全部可用节点数量**: `{TOTAL_COUNT}` 个  
> 🏠 **甄选家宽节点数量**: `{RES_COUNT}` 个  
> 👤 **定制规范命名**: 所有订阅节点均重命名为 `国旗 地区 序号 (家宽) - xiaohe`  
> ⚡ **真实可用保障**: 所有节点由 `mihomo` 代理内核建立实际网络通道握手测活，拒绝虚假通畅与死节点。

---

## 📌 全部节点总订阅链接

| 客户端 / 格式 | 节点总数 | 免翻 CDN 直链 (国内直连) | 原生 Raw 直链 (开启代理) |
| :--- | :---: | :---: | :---: |
| 🚀 **Clash (YAML)** | `{TOTAL_COUNT}` | [点击使用免翻 CDN 直链](https://cdn.jsdelivr.net/gh/{REPO_NAME}@main/output/clash.yaml) | [点击使用官方原生 Raw 直链](https://raw.githubusercontent.com/{REPO_NAME}/main/output/clash.yaml) |
| ⚡ **V2Ray (Base64)** | `{TOTAL_COUNT}` | [点击使用免翻 CDN 直链](https://cdn.jsdelivr.net/gh/{REPO_NAME}@main/output/v2ray.txt) | [点击使用官方原生 Raw 直链](https://raw.githubusercontent.com/{REPO_NAME}/main/output/v2ray.txt) |
| 📦 **sing-box (JSON)** | `{TOTAL_COUNT}` | [点击使用免翻 CDN 直链](https://cdn.jsdelivr.net/gh/{REPO_NAME}@main/output/singbox.json) | [点击使用官方原生 Raw 直链](https://raw.githubusercontent.com/{REPO_NAME}/main/output/singbox.json) |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 经 MaxMind ASN 数据库与 rDNS 宽带特征探测，排除所有云主机/数据中心，保留真实民用宽带。

| 地区/国家 | 节点数 | 通用 Base64 | Clash (YAML) | sing-box (JSON) |
| :--- | :---: | :---: | :---: | :---: |
{RES_TABLE}

---

## 🗺️ 按照国家分类节点订阅 (全部可用节点)

| 地区/国家 | 节点数 | 通用 Base64 | Clash (YAML) | sing-box (JSON) |
| :--- | :---: | :---: | :---: | :---: |
{COUNTRY_TABLE}

---

## 🔒 私有仓库（Private）无感免翻订阅方案 (基于 Cloudflare Workers)

> 如果你希望将本 GitHub 仓库设置为 **Private (私有仓库)** 保护节点资产，外部客户端无法直接拉取原生 Raw 或公共 CDN 链接，可以通过以下 Cloudflare Worker 搭建轻量级私密网关反代：

### 1. 获取 GitHub 永久个人令牌 (PAT)
1. 进入 GitHub -> **Settings** -> **Developer Settings** -> **Personal access tokens (classic)**。
2. 点击 **Generate new token (classic)**，勾选 `repo` 权限，有效期设为 `No expiration`（永不过期）。
3. 复制保存生成的以 `ghp_` 开头的 Token。

### 2. 部署 Cloudflare Worker
登录 Cloudflare Dashboard，创建一个新的 Worker，复制以下脚本粘贴并部署：

```javascript
export default {
  async fetch(request) {
    const GITHUB_TOKEN = "ghp_你的GitHub永久访问令牌"; // 填入第1步生成的Token
    const OWNER = "{OWNER}";
    const REPO = "{REPO}";
    const BRANCH = "main";

    const url = new URL(request.url);
    const filePath = "output" + url.pathname;
    const ghUrl = ["https:", "", "raw.githubusercontent.com", OWNER, REPO, BRANCH, filePath].join("/");
    
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
