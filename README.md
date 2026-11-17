# content-diet

> 把「你的口味」变成每周/每月的飞书卡片：番剧、网文、音乐、任天堂新作。
> 丢给 agent，它自己问、自己配、自己排期。

## 它解决什么

推荐列表的通病是"给所有人推同一批热门"。这个包换了个做法：

1. **先做访谈**——不是问"你喜欢什么题材"，是问"你受不了什么""你在追什么""哪批是陪你长大的"
2. **生成一份口味档案**（`profile.json` + 可读版 `taste_profile.md`），后面所有筛选都读它
3. **抓公开数据源**（Bangumi / 起点 / 网易云 / 任天堂香港），**全部不需要登录**
4. **按排期发飞书卡片**，没有新内容就一个字不发

## 谁在用、用什么

| 卡片 | 内容 | 频率 |
|---|---|---|
| 📺📖 片单卡 | 当季番剧（评分 + 口味匹配理由）+ 网文月票榜 | 每周 |
| 💿 新发行 | 你"主动等新作"的那几位歌手的新专辑（带封面） | 每月 |
| 🎮 任天堂香港 | 近期发售，筛掉资产翻新/AI 图小作，带海报 | 每周 |

## 给 agent 的一句话

```
读 SKILL.md，按里面的五步给我装好 content-diet，访谈我想做「普通」深度。
```

agent 会：体检 → 访谈（可跳过/大概/普通/细致）→ 写档案 → 告诉你需要哪几个 token（**可选**，不给就少点能力）→ 建定时任务 → 先试发一张给你看。

## 给人类：手动装

```bash
git clone <this-repo> content-diet && cd content-diet
python3 setup/doctor.py --fix          # 体检 + 生成 .env 模板
cp .env.example ~/.content-diet/.env   # 或者直接编辑 doctor 生成的那份
# 填好 FEISHU_*，然后
python3 setup/doctor.py --send-test    # 真发一条，确认手机能收到
python3 setup/init.py --answers answers.json
python3 -m cards.weekly --preview      # 干跑看数据
python3 -m cards.weekly                # 真发一张
```

没有 `answers.json`？先跑 `python3 setup/init.py --example` 看模板，或者让 agent 访谈生成。
手里只有一份旧的 `taste_profile.md`？照 `references/taste-schema.md` 反推 `answers.json`
（`anime_watched` 留空），别重做一小时访谈。

卡片发过之后想标「看过了 / 不想看」：

```bash
python3 setup/mark.py seen anime 葬送的芙莉莲
python3 setup/mark.py skip novel 玄鉴仙族
python3 setup/mark.py list
```

回写落在 `$CONTENT_DIET_HOME/feedback.json`，和档案合并生效（改档案不会冲掉它）。

自检（全部离线，不连网不花钱）：

```bash
python3 -m unittest discover -s tests -v
```

## 零凭据也能跑

四个数据源都是公开页面/接口：Bangumi API、起点移动端月票榜、网易云公开检索、任天堂香港发售表。
没有飞书凭据时，卡片退化成打印文本（`--no-send`），体验不打折，只是不推送。

可选凭据与"不给会少什么"：见 [`references/tokens.md`](references/tokens.md)。
`BGM_API_TOKEN` / `QIDIAN_COOKIE` 目前只是留位（代码还没读它们），排重靠档案 + `setup/mark.py`。

## 网络与代理（换机第一次跑就卡在这）

这台机器上 Bangumi 的 API 和图床**直连不通**，不设代理时第一条命令就是：

```
RuntimeError: Bangumi 搜索失败: <urlopen error [Errno 101] Network is unreachable>
```

代码认两个变量，随便设一个：

```bash
export CONTENT_DIET_PROXY=http://127.0.0.1:7890     # 优先
# 或者沿用系统代理
export HTTPS_PROXY=http://127.0.0.1:7890
```

写在 `$CONTENT_DIET_HOME/.env` 里也可以（`CONTENT_DIET_PROXY=http://host:port`）。
脚本对每个请求都是「先直连，失败再走代理一次」，所以设了不影响本来能直连的源
（起点移动端、网易云、任天堂香港）。**不需要代理的环境就别设**——设了只是多一次失败重试。

`doctor` 报源不可达时也会提醒这一条；`--json` 输出里 `proxy` 字段能看到当前生效值。

## 结构

```
SKILL.md                  agent 入口：五步初始化 + 踩坑清单 + 排版硬规则
setup/
  doctor.py               体检：源可达性 / 凭据 / 卡片可用性 / --send-test
  interview.md            访谈题本（跳过 / 大概 / 普通 / 细致 四档）
  init.py                 访谈结果 → profile.json + taste_profile.md + 排期建议
  mark.py                 回写「已看 / 不想看」→ feedback.json
  feishu_chats.py         列出机器人所在会话，拿 chat_id
  feishu_from_dsh_im.py   复用 dsh-im 已有机器人凭据（secretRef 精确取值）
  poster_sheet.py         海报拼成带编号对比图（判断"AI 垃圾"用）
sources/
  bangumi.py              当季番剧搜索 + 打分（排斥/加分词读档案）
  qidian.py               起点月票榜（分类偏好、作者权重建档驱动）
  nintendo_hk.py          任天堂香港发售表 + 口味分层 + seen 基线
cards/
  weekly.py               片单卡（番剧 + 网文）
  music.py                内核层新发行月报（名单只从档案来）
  games.py                任天堂新作卡
core/
  config.py               路径与凭据（全部走 $CONTENT_DIET_HOME）+ 档案 / 回写读取
  feishu.py               飞书卡片：token / 上传 / 发送（检查返回码）/ 排版 helper
  sent.py                 周期卡去重（同周期同内容只发一次）
tests/
  test_content_diet.py    离线用例：档案驱动筛选、失败非 0、去重、payload 契约
references/
  tokens.md               每个 token 怎么拿、能多什么、不给少什么
  taste-schema.md         answers.json / profile.json / feedback.json 字段说明
```

## 几条设计取舍（不是没做，是想过）

- **只推公开数据**，不碰需要登录的推荐流。代价是拿不到"个性化"，收益是不会因为反爬失效而整张卡崩。
- **音乐不按周推**。整张专辑式消费的人，周推单曲就是噪音；月报只报"你等的那几位有没有新东西"。
- **不做自动下单/抢票/代注册**。需要人机验证的环节一律交回用户。
- **不猜**。抓不到就说抓不到；空字段 = 不筛，而不是编一个默认偏好。

## License

MIT

---

## 在 DeepSeek Harness（DSH）里运行

DSH 的沙箱、定时任务、技能发现都和裸机 shell 不一样。照下面五点做，不然会在三处踩空。

### 1. 权限与状态目录（最常踩）

DSH 默认 `workspace-write`：工作区外（含 `$HOME`）不可写，**不弹审批直接 `Operation not permitted`**。
所以第一步先定一个可写目录：

```bash
export CONTENT_DIET_HOME="$PWD/.content-diet"
```

或者让用户在会话里切到「完全权限」。**不要把「默认 `~/.content-diet`」当成一定能写。**
只读环境下 `--preview` / `--no-send` 仍能出卡（缓存写不进去就降级），但要写 `.env` / `profile.json` 就必须先设这个变量。

### 2. 定时任务用 DSH 自带 `schedule`，不要 cron

`crontab` 在沙箱里 exit 126，`~/Library/LaunchAgents` 也写不进去。用 DSH 的 `schedule_create`（rrule）：

```
DTSTART;TZID=Asia/Shanghai:20261122T200000
RRULE:FREQ=WEEKLY;BYDAY=SU;BYHOUR=20;BYMINUTE=0
```

prompt 里写清 cwd 与状态目录：

```bash
cd <repo> && CONTENT_DIET_HOME=<repo>/.content-diet python3 -m cards.weekly
```

要点：`target=new_once`；DSH 进程要常驻，停机后只补最近一次；**没有新内容时让 agent 明确回「本周无更新」**，
否则绑了 IM 的 session 里空输出也会触发一条投递通知（噪音）。

### 3. 技能发现

DSH 只从**已安装插件**的 `skills/<name>/SKILL.md` 发现技能，裸 `git clone` 不会自动出现在技能列表里。二选一：

- README 明说「把仓库里的 `SKILL.md` 路径贴给 agent」；
- 或发布成 DSH bundle（`package.json` 带 `dsh.bundle`，`skills/content-diet/SKILL.md` 指回脚本）。

### 4. 推荐插件：`@xmanrui/dsh-im`（飞书通道）

它已经处理了建应用、扫码授权、长连接、私聊/群 chat_id，**这个包可以复用同一只机器人**，
不用让朋友再建第二个飞书应用（见 `references/tokens.md` 第 1 节与 `setup/feishu_from_dsh_im.py`）。
零配置兜底：`POST http://127.0.0.1:<port>/api/dsh-im/delivery/messages` 只发文字摘要（不支持 interactive 卡片）。

### 5. 一个容易误判的小坑

macOS + DSH 沙箱里 `git clone` 会先打印
`fatal: unable to get credential storage lock in 1000 ms: Operation not permitted`，
**但 clone 实际成功**——别以为下载失败。
