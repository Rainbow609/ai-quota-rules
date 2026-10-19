# ai-quota-rules — AI 订阅 / API 额度查询规则集

给客户端（鸿蒙 Next App、桌面小组件、CLI 等）用的**声明式规则集**：某家 AI 服务的额度/余额/用量该请求哪个接口、怎么鉴权、响应字段怎么映射、套餐是否区分高峰时段。

本仓库是**唯一真源**，客户端只拉取、不内置业务逻辑；规则更新不需要发版。

> Rules-as-data for querying AI subscription & API quota: endpoints, auth, field mapping, peak-hour windows. Data only — no scripts, no expression engine.

## 目录结构

```
rules/providers/*.json     # 每家服务一个文件（人读、PR diff 友好）
rules/holidays/cn.json     # 中国大陆法定节假日（影响 DeepSeek 平峰判定）
schema/ruleset.schema.json # 构建产物 schema
mirrors/mirrors.json       # 客户端多源拉取清单（可远程更新，无需发版）
tools/build.py             # rules/ -> dist/ruleset.json + dist/manifest.json
tools/validate.py          # 结构 + 语义校验（CI 与本地同款，仅用标准库）
dist/                      # 构建产物（CI 自动提交，客户端实际拉取的文件）
.github/workflows/publish.yml
```

## 客户端接入

1. 先拉 `mirrors/mirrors.json`（若已有），按其中 `sources[]` 的 `priority` 顺序取 `dist/manifest.json`（约 0.5 KB）。
2. `manifest.version` 比本地新，才拉 `dist/ruleset.json` 全量；否则结束。
3. **必须做完整性校验**：`sha256(body) == manifest.checksum.sha256`；`ruleset_version` 单调递增；`min_client_version <= 本机版本`。
4. 内置一份兜底副本（随 App 打包）→ 磁盘缓存（双槽 current/previous）→ 内存态。**任何一步失败都保留上一版，绝不写入半成品**（原子写：临时文件 → rename）。

### 国内可达性（2026-10-19 调研，未在大陆网络实测）

| 优先级 | 源 | 说明 |
| --- | --- | --- |
| 1 | Gitee raw（需自建镜像仓库） | 免备案、大陆直连最稳；同步需手动或定期；**有被下架先例，不能作唯一源** |
| 2 | npmmirror（`registry.npmmirror.com/<pkg>/<ver>/files/<path>`） | 免备案、大陆直连稳；需先发 npm 包；无 ETag，用 `@version` 寻址 |
| 3 | jsDelivr 四主机轮换（`cdn` / `fastly` / `testingcf` / `gcore`.jsdelivr.net） | 可用但不稳；分支缓存 12 小时；**限流时返回 HTTP 200 + 正文 `429: Too Many Requests`，必须按"正文非 JSON"判失败** |
| 4 | ghproxy 池（gh-proxy.com / ghfast.top / ghproxy.net …） | 境外反代，只能兜底；节点会漂移，清单放 `mirrors.json` 远程更新，勿硬编码进 App |
| 5 | raw.githubusercontent.com | 大陆不可依赖；仅海外/开发期 |

其它结论：`raw.gitmirror.com` / `hub.gitmirror.com` 域名已失效（NXDOMAIN）；Cloudflare Pages/R2/Workers 不在中国大陆网络内（China Network 是 Enterprise 独立订阅且要求 ICP 备案），不能当大陆主通道；要走"备案域名 + 境内 CDN"才有稳定体验（腾讯云 CDN 大陆流量约 ¥0.21/GB 起步，规则集是小文件高频拉取，务必用 ETag/304 把流量压下来）。

### 客户端拉取策略建议

- 单次刷新总预算 20–25 秒、最多尝试 3 个源；失败就等下次定时（不要 6 个源全部轮一遍）。
- 失败分类：`404/410` 立即换源；`403/5xx/超时/Cloudflare 挑战页` 换源；**TLS 证书错误 → 该源本次禁用（防中间人）**。
- 源级退避：某源连续失败则跳过 12 小时（本地持久化），成功即清零；记住上次成功的源，但每周强制从源 1 重新探测。
- 刷新时机：启动时 + 前台；避免后台被系统挂起后反复重试。规则更新频率低，12 小时粒度足够。

## 规则集形状

见 `schema/ruleset.schema.json` 与 `dist/ruleset.json`。要点：

- `providers[].queries[]`：`method` + `base` + `path` + `auth`，`values[]` 用**受限路径语法**（点号 + `[n]` 下标）描述取值，例如 `usage.rolling.percent`、`model_remains[0].current_interval_remaining_percent`。
  **规则只能是数据**：不含脚本、不含表达式、不含模板引擎——远端内容不得具有可执行语义。
- `providers[].peak`：高峰时段（`days` 1=周一 … 7=周日、`start`/`end` 本地时间、`timezone` IANA），可挂 `holiday_calendar`（节假日全天按平峰）。客户端可**离线**算出"当前是否高峰"。
- `confidence` / `sources[]`：区分官方文档与社区逆向，客户端可据此决定展示口径。
- `kind`：`balance`（余额制）/ `subscription`（套餐制，看窗口剩余百分比）。

## 维护

```bash
python3 tools/validate.py            # 校验
python3 tools/build.py               # 生成 dist/
```

新增一家：在 `rules/providers/` 加一个 JSON（照抄同类推），跑上面两条命令，PR。CI 会校验并自动重建 `dist/`。

## 免责声明

多数套餐额度接口**未在厂商官方 API 文档中公开**（来自社区逆向或官方 CLI 源码），可能随时变更；本文档标注 `confidence` 字段以示区分。使用本规则集造成的任何后果由使用者自负。规则集的目的是让用户查看**自己账号**的额度，不涉及绕过任何计费或访问控制。

## License

MIT
