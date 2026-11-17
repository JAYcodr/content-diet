---
name: content-diet
description: Use when setting up per-user taste-based media digests.
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [content, recommendations, feishu, cards, cron, taste]
---

# content-diet · 把「内容口味」变成定期卡片

你是被叫来跑初始化的 agent。这个包做的事：**问清用户口味 → 生成档案 → 抓公开数据源 → 排期发飞书卡片**。
已经踩过的坑都写在下面，照做能省掉你半小时试错。

## 0. 先搞清楚这是什么

| 模块 | 作用 | 是否需要凭据 |
|---|---|---|
| `sources/bangumi.py` | 番剧当季榜 + 评分 + 标签（Bangumi 公开 API） | 不需要（令牌可选） |
| `sources/qidian.py` | 起点月票榜（移动端）+ 书架（Cookie 可选） | Cookie 可选 |
| `sources/nintendo_hk.py` | 任天堂香港发售表 + 海报 | 不需要 |
| `cards/music.py` | 内核层歌手新专辑月报（网易云公开接口） | 不需要 |
| `cards/weekly.py` | 片单卡：番剧 + 网文 | 需要飞书凭据 |
| `cards/games.py` | 任天堂新作卡（带海报） | 需要飞书凭据 |
| `setup/doctor.py` | 体检：源可达性、凭据、卡片可用性、`--send-test` 真发一条 | — |
| `setup/init.py` | 把访谈结果写成 profile.json + taste_profile.md，并给出排期 | — |
| `setup/mark.py` | 回写「已看 / 不想看」（feedback.json），参与下一轮排重 | — |

**零凭据也能跑**：所有数据源都是公开页面/接口，没凭据时卡片退化成打印文本（`--no-send`）。
**没有任何内置口味名单**：艺人、作者、排斥词、分类全部来自档案；档案空就不筛（音乐卡直接不排）。

## 1. 初始化五步（按顺序，别跳）

### 第 1 步：体检

```bash
python3 setup/doctor.py --fix
```

看三件事：源是否可达、`FEISHU_*` 是否已配、有没有装 Pillow（任天堂海报拼图用）。
某些网络下 Bangumi 必须走代理：`export CONTENT_DIET_PROXY=http://host:port`。

**沙箱权限（DSH 默认 `workspace-write`，$HOME 不可写）**：第一步就设可写状态目录，
`export CONTENT_DIET_HOME=$PWD/.content-diet`。不设的话 `--fix` 会给你一句可照做的提示（不是 traceback）；
`--preview` / `--no-send` 在只读环境下仍能出卡（缓存降级），但写 `.env` / `profile.json` 必须先设。
完整说明见 README「在 DeepSeek Harness（DSH）里运行」。

### 第 2 步：访谈（**先把这一步做对，后面全是自动的**）

读 `setup/interview.md`，按用户选的深度提问。四档：

| 档位 | 问什么 | 耗时 |
|---|---|---|
| `skip` | 不问，用通用口味跑（卡片能出，但推荐偏大众） | 0 |
| `rough` | 3 个问题：最爱 3 部 / 最讨厌 3 部 / 主要看什么媒介 | 1 分钟 |
| `normal` | 分媒介各 2–3 题：番剧、网文、音乐、游戏 | 5 分钟 |
| `detailed` | 逐条对齐「体验距离 + 排斥信号 + 层次结构」，可追问 | 15 分钟 |

**问法要点**（这是整套东西的质量开关）：

- 不要问「你喜欢什么题材」，要问**「你受不了什么」**——排斥信号比喜好更能筛掉噪音。
- 不要问「喜欢哪首歌」，要问**「最近常整张循环的专辑 / 艺人」**——单曲和专辑是两种消费。
- 要问**「你在追什么」**（具体的书名、番名），这是排重名单，比任何标签都准。
- 要问**「有没有"陪伴型"的艺人」**（从小听到大、熟到不用记的那些）——这类**不能推**，推了是噪音。

把答案整理成 `answers.json`（字段见 `references/taste-schema.md`，或 `python3 setup/init.py --example` 看模板）。

**已经有 `taste_profile.md`（换机 / 重装）？别重做访谈**，先反推 `answers.json`：

1. 打开那份 md，按 `references/taste-schema.md` 的表格逐字段对号入座——
   「内核层」→ `core_artists`、「陪伴型」→ `companion_artists`、「已读 / 在追」→ `novels_read`、
   「弃书」→ `novels_dropped`、「偏好分类」→ `novel_categories`。`setup/init.py --answers` 现成支持。
2. **`anime_watched` 一律留空**，等 `bgm_sync` 补齐。md 里「番剧」那节的命中列表是推荐结果，
   不是已看记录；抄进去的直接后果是「推给你的全是你已经看过的」。宁可这几周多推两条重复的。
3. 反推完把 `answers.json` 给用户过一眼再落盘——人名书名抄错比空着更难发现。

**回写比访谈重要**：卡片发出去之后，用户说「这个看过了 / 不想看」，
就 `python3 setup/mark.py seen anime 作品名`（或 `skip`）记下来，下一轮筛选自动排掉。
这条路径不依赖卡片按钮，也不依赖任何登录。

### 第 3 步：生成档案

```bash
python3 setup/init.py --answers answers.json --name "用户称呼"
```

写出两样东西到 `$CONTENT_DIET_HOME`（默认 `~/.content-diet`）：

- `profile.json`：给脚本读的机器档案（排重名单、内核层艺人、偏好分类）
- `taste_profile.md`：给人读的口味白皮书

同时打印**建议排期**。

### 第 4 步：凭据（可选，但要告诉用户"不给会少什么"）

读 `references/tokens.md`，逐项告诉用户：怎么拿、要几分钟、不给的话损失什么。
**不要一次甩六个**——先只要飞书的三个（否则发不出卡片），其余按用户意愿追加。

| 凭据 | 必需性 | 给了之后真实效果 |
|---|---|---|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` | 必需 | 发卡片；`doctor --send-test` 能证明这条链路通 |
| `BGM_API_TOKEN` | 可选 | **当前代码没读它**（只留位：限流 + 收藏接口是待办）；填了 doctor 会标「已填写，但代码还没读」 |
| `QIDIAN_COOKIE` | 可选 | **当前代码没读它**；在追名单靠档案 + `setup/mark.py` 回写，不靠 Cookie |
| `NETEASE_COOKIE` | 可选 | 暂时用不到，留位 |

凭据只进 `$CONTENT_DIET_HOME/.env`（600），**不要打进聊天、不要写进仓库**。
填完飞书三项，**一定跑一次 `python3 setup/doctor.py --send-test`**——凭据在 ≠ 机器人那个群里。

### 第 5 步：排期 + 首轮试跑

```bash
# 先干跑，确认数据对，不发消息
python3 -m cards.weekly --preview
python3 -m cards.music --days 60 --no-send
# 再真发一次
python3 -m cards.weekly
```

跑通后再建定时任务（按宿主 agent 的能力建）：

- **裸机**：cron / systemd timer
- **DSH**：用自带 `schedule`（rrule），**不要 crontab**——沙箱里 exit 126；prompt 里写清
  `cd <repo> && CONTENT_DIET_HOME=<repo>/.content-diet python3 -m cards.weekly`
- **DSH 技能发现**：裸 `git clone` 不会出现在技能列表里，要么把 SKILL.md 路径贴给 agent，
  要么发布成 DSH bundle。

| 卡 | 频率 | 命令 |
|---|---|---|
| 片单卡（番剧 + 网文） | 每周日 20:00 | `python3 -m cards.weekly` |
| 任天堂新作 | 每周四 20:00 | `sources/nintendo_hk.py --new > nk.json` → 审查 → `python3 -m cards.games --data nk.json` → `nintendo_hk.py --commit --from-payload nk.json` |
| 音乐新发行 | 每月 1 日 10:00 | `python3 -m cards.music --days 45`（档案里没 `core_artists` 时这张卡不存在） |

**任天堂卡别用 `--commit --all`**：它会把这一轮没发出去的白名单条目、没审的 review
一次性记成已见，下周就不再出现。记基线只提交「真发出去的」：`--commit --from-payload <那份 payload>`
（发卡前删掉 AI 垃圾条目后，payload 就是「真处理过」的名单）；不传 path 时 `--commit` 读上一次
`--new` 自动写的 `pending.json`。

**周期卡自带去重**：同一周（月）同一份内容补跑第二次会直接跳过并打印上次的 `message_id`，
真要重发加 `--force-send`。

**静默原则**：没有新内容就一个字都不发（脚本空输出 = 不投递）。用户嫌吵的话，先砍频率，别砍卡片质量。

## 2. 数据源的坑（实测，别重踩）

| 源 | 坑 | 解法 |
|---|---|---|
| Bangumi API | 部分网络**直连不通**，必须代理 | `CONTENT_DIET_PROXY` |
| Bangumi `/calendar` | 不返回 tags，没法打分 | 用 `POST /v0/search/subjects` 带 `air_date` 区间 |
| Bangumi 封面 | `lain.bgm.tv` 同样需要代理 | 下载时带 Referer |
| 起点桌面站 | **WAF**：curl 202 空页、浏览器 0 字节 | 走移动端 `m.qidian.com` + iPhone UA |
| 起点书架 | SPA，服务端页面没有数据 | 用户 Cookie 注入浏览器后读 `my.qidian.com/bookcase` |
| 网易云 | 连续请求会 `406 操作频繁` | 请求间隔 ≥1.2s + 退避重试；艺人 id 缓存 |
| 任天堂 HK | 海报在 `style="background-image:url(...)"`，**右括号常被优化掉** | 用 `url\(([^"')\s]+)` 抓 |
| 任天堂详情页 | 价格/截图/预告片是前端渲染，抓不到 | 判断"是不是 AI 垃圾"只能看海报美术 |
| 海报拼图 | 需要 Pillow | 没装就跳过拼图，直接抽看 |

## 3. 打分与筛选的原则（决定卡片好不好看）

1. **标签命中全额、标题命中的折半、简介不参与打分**。简介里随手一提"料理"会把无关作品顶上来。
2. **排斥信号一票否决**，不要试图"综合评估"——用户说讨厌降智爽文，就别给他看降智爽文。
3. **已看/已读/已弃的书名优先排重**，比标签准得多。
4. **分类轮转**：同一分类最多 2 条，否则一张卡全是科幻。
5. **音乐只推内核层**；陪伴型（从小听到大那批）**永不推**。给专辑不给单曲。
6. **垃圾游戏靠看海报**：拼成带编号的对比图，一次判断"正规美术 vs 廉价资产翻新"（构图空、塑料 3D、比例怪异、排版粗糙、通用剪影）。

## 4. 卡片排版（飞书 Card JSON 2.0）

用 `core/feishu.py` 的 helper，别手写 JSON：

```python
from core.feishu import card_v2, md, img, cols, footer, send_card, upload_image
card = card_v2(title="本周片单", subtitle="番剧 4 · 网文 4",   # 标题别写人名，要写就取 config.display_name()
               template="turquoise", elements=[
                   md("**📺 番剧**"),
                   cols((1, [img(key, size="96px 136px", radius="6px")]), (3, [md("...")])),
                   footer("数据源 Bangumi / 起点月票榜"),
               ])
send_card(chat_id, card)      # 返回 data（含 message_id）；code != 0 会抛异常，不会静默成功
```

硬规则（都踩过）：

- 表格**列宽必须给百分比**，`auto` 会撑出卡片被右边缘裁掉
- 图片**必须给 `size`**，否则铺满整宽；限宽最省事的办法是塞进 `column_set`
- **按钮必须放在 column 里**，放根节点会变满宽纵向堆叠
- 2.0 不支持 `tag: action` 容器，也**不支持 markdown 表格**
- 回读接口拿到的是 v1 降级表示（"请升级客户端"），**不能当渲染证据**，效果只能让用户截图确认

## 5. 扩展

- 加数据源：照 `sources/` 里任一文件写 `fetch()/parse()`，别把网络请求写进卡片层。
- 加卡片：照 `cards/weekly.py`，`--preview` 必须能只打 JSON 不发消息（调试用）。
- 所有路径走 `core/config.py`（`state_dir()` / `profile_list()`），**不要在代码里写死绝对路径**。

## 6. 交付前自检

```bash
python3 -m unittest discover -s tests -v     # 31 条离线用例：档案驱动、失败非 0、去重、契约
python3 setup/doctor.py                      # 源与凭据
python3 setup/doctor.py --send-test          # 真发一条，证明手机能收到
python3 -m cards.weekly --preview | head -20
python3 -m cards.music --days 60 --no-send
```

`tests/` 全部离线（不连网、不花钱、不碰真实状态目录），改完筛选逻辑先跑它。
都过之后再真发一张给用户看。
