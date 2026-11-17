# 凭据获取指南

全部凭据只写在 `$CONTENT_DIET_HOME/.env`（默认 `~/.content-diet/.env`，权限 600）。
**不要**写进仓库、不要贴在聊天里。agent 只读环境变量，不回显值。

---

## 1. 飞书（必需，否则发不出卡片）

### 已经有机器人？直接复用，别建第二个

如果你的 DSH 里已经装好飞书通道插件 `@xmanrui/dsh-im`，**不用再建应用**：

- appId / secret 用同一只机器人的（它已经把建应用、扫码授权、权限、长连接、chat_id 全做完了）
- 发送消息**不需要长连接**，不会和 dsh-im 抢事件
- `chat_id` 可以在 dsh-im 的设置页「投递目标 → 从已聊会话选择」里直接选，不需要 `feishu_chats.py`
  （那个脚本要求 `im:chat:readonly`，dsh-im 的应用未必开了这个权限）

自动取凭据：

```bash
python3 setup/feishu_from_dsh_im.py --dry-run   # 先看能读到什么
python3 setup/feishu_from_dsh_im.py             # 读到就写进 .env
```

它按 dsh-im 的真实结构读：`~/.dsh/integrations/dsh-feishu/config.json` 的 `bots[].appId`
（多个机器人时挑 `activated` 的那个），再用同一项的 `secretRef` 去 `~/.dsh/.credentials.yaml`
的 `refs:` 里取对应密钥——`secretRef` 只是键名，**不能按位置取 refs 第一条**（那里可能是
别的服务的 key）。读不到会打印手动配置的两行，不会报错。**卡片发不出去时的兜底**：dsh-im 还有独立的文字投递接口
（`POST http://127.0.0.1:<port>/api/dsh-im/delivery/messages`，只支持 plain/markdown，不支持 interactive 卡片），
可以当降级路径，但别写成默认——卡片是这个包的卖点。

### 没有机器人？自己建一个

要做三样：建应用、开权限、拿 chat_id。

### 1.1 建应用拿 App ID / Secret

1. 打开 <https://open.feishu.cn/app> → **创建企业自建应用**（名字随便，比如「内容片单」）
2. 进应用 → 「凭证与基础信息」→ 复制 **App ID** 和 **App Secret**

### 1.2 开权限（少一个都发不出去）

「权限管理」→ 搜索并添加：

| 权限 | 用途 |
|---|---|
| `im:message` | 发送消息 |
| `im:resource` | 上传图片（卡片封面） |
| `im:chat:readonly` | 列出机器人所在的群（用来找 chat_id，可选） |

然后「版本管理与发布」→ 创建版本 → 提交 → **等管理员审批通过**（自己是管理员就直接过）。

### 1.3 拿 chat_id

两条路，任选：

- **群聊**：把机器人拉进群 → 群设置 → 群链接里 `openChatId=oc_xxx` 那段就是
- **私聊**：先给机器人发一条消息，然后

  ```bash
  python3 setup/feishu_chats.py        # 列出机器人所在的会话及 chat_id
  ```

填进 `.env`：

```env
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxx
```

### 1.4 验证：真发一条

凭据填对 ≠ 能送到（chat_id 填错、机器人没进群，doctor 全绿也会空手）。所以：

```bash
python3 setup/doctor.py --send-test
```

输出 `✓ 凭据有效，消息已送达 oc_xxx（message_id om_xxx）` 且手机真收到，才算这条链路通了。
失败时它会告诉你按什么顺序查（chat_id 前缀、机器人是否在群里、应用是否发过版本 + `im:message`）。
另外 `feishu_from_dsh_im.py --verify` 会在写 `.env` 前后各换一次 `tenant_access_token`，
证明 secret 真的对（不是「读到了一个 32 字符的字符串」）。

> 常见报错：`99991663` 权限没开或版本没发布；`230002` 机器人不在该会话里（先拉进群）。

---

## 2. Bangumi 个人令牌（可选，**当前代码还没用**）

填了也不生效——现在的 `sources/bangumi.py` 只打公开接口，没有带 `Authorization`，
也没有接收藏接口。真要用上它（提高限流 + 读收藏做排重）还得改代码，属于待办。

想让番剧排重更准，眼下更实际的做法是：访谈时把「已看」写进档案，之后用
`python3 setup/mark.py seen anime 作品名` 逐条回写。

1. 登录 <https://bgm.tv>
2. 打开 <https://next.bgm.tv/demo/access-token> → 生成 Access Token
3. 填 `BGM_API_TOKEN=...`（留位；doctor 会标成「已填写，但代码还没读」）

> 令牌是 Bearer token，只读公开数据 + 自己的收藏，不会改任何东西。

---

## 3. 起点 Cookie（可选，**当前代码还没用**）

同样留位：`sources/qidian.py` 只读移动端月票榜页面，不读 Cookie，也没有「在追」接口。
「不知道用户在追什么」这件事靠档案（访谈里的在追名单）+ `setup/mark.py` 回写解决，
不是靠 Cookie。

1. 浏览器登录 <https://www.qidian.com>
2. F12 → Network → 刷新 → 点任意请求 → 复制 **Request Headers 里的 Cookie 整串**
3. 关键项：`ywguid`、`ywkey`、`ywopenid`（其余可带可不带）
4. 填 `QIDIAN_COOKIE=ywguid=...; ywkey=...; ywopenid=...`

> 有效期通常几周到几个月。将来接「书架 / 在追」时会用到；现在填了 doctor 也只标「留位」。

---

## 4. 网易云 Cookie（可选，暂时用不到）

音乐月报只用公开接口（艺人专辑 + 封面）。留位给将来的「相似艺人 / 每日推荐」，
开放接口需要登录态（`/api/discovery/simiArtist` 未登录返回 `code 301`）。

---

## 5. 代理（视网络环境）

Bangumi 的 API 与图床在某些网络下**直连不通**。需要时：

```env
CONTENT_DIET_PROXY=http://127.0.0.1:7890
```

脚本对每个请求都是「直连失败 → 走代理重试一次」，所以设了不影响能直连的源。

---

## 6. 缺凭据时的降级矩阵

| 缺什么 | 结果 |
|---|---|
| 飞书三项 | 卡片发不出去，`--no-send` / `--preview` 仍可用（打印文本 / JSON） |
| `BGM_API_TOKEN` | **没有变化**（代码还没读它）；番剧排重靠档案 + `setup/mark.py` |
| `QIDIAN_COOKIE` | **没有变化**（代码还没读它）；在追名单靠访谈 + `setup/mark.py` |
| 档案里的 `core_artists` | 音乐月报直接跳过（不回落默认艺人名单） |
| `CONTENT_DIET_PROXY` | 直连不通的源会整段缺失（doctor 会标出来并提示设代理） |
| 状态目录不可写 | 出卡照旧，但封面每次重下、`seen` / 回写 / 去重不落地（stderr 会提示一次） |
