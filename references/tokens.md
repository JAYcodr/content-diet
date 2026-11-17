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

> 常见报错：`99991663` 权限没开或版本没发布；`230002` 机器人不在该会话里（先拉进群）。

---

## 2. Bangumi 个人令牌（可选）

没有它也能抓当季番剧，只是：限额低、读不到用户收藏（排重靠 profile 里的名单）。

1. 登录 <https://bgm.tv>
2. 打开 <https://next.bgm.tv/demo/access-token> → 生成 Access Token
3. 填 `BGM_API_TOKEN=...`

> 令牌是 Bearer token，只读公开数据 + 自己的收藏，不会改任何东西。

---

## 3. 起点 Cookie（可选，但强烈建议）

没有它：网文按榜单纯推，**不知道用户在追什么，会重复推**。

1. 浏览器登录 <https://www.qidian.com>
2. F12 → Network → 刷新 → 点任意请求 → 复制 **Request Headers 里的 Cookie 整串**
3. 关键项：`ywguid`、`ywkey`、`ywopenid`（其余可带可不带）
4. 填 `QIDIAN_COOKIE=ywguid=...; ywkey=...; ywopenid=...`

> 有效期通常几周到几个月。**过期表现**：书架抓取返回 0 本 / 登录态消失。
> 更新方式：重新复制一次 Cookie 覆盖即可，不用改代码。

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
| `BGM_API_TOKEN` | 番剧段正常，但不禁"已看"，可能推重复 |
| `QIDIAN_COOKIE` | 网文段正常，但可能推用户正在追的书 |
| `CONTENT_DIET_PROXY` | 直连不通的源会整段缺失（doctor 会标出来） |
