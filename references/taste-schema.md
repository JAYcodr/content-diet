# 档案字段说明

两样东西：

- `answers.json`：**你（agent）从访谈里整理出来的原始答案**，喂给 `setup/init.py`
- `profile.json` + `taste_profile.md`：**init 生成的档案**，脚本和卡片读这个

**每个字段都真的会被读**：写进档案的排斥词会改变打分，偏好分类会改变榜单抓取，
内核层艺人决定音乐月报推谁。没有「写了但代码不认」的字段——想加新词就改档案，不用改代码。

## answers.json

| 字段 | 类型 | 说明 | 谁来读它 |
|---|---|---|---|
| `depth` | `skip`/`rough`/`normal`/`detailed` | 访谈深度，只记录用 | — |
| `name` | 字符串 | 用户在卡片标题里的称呼；留空 = 中性标题（「本周片单」） | 一周/一月卡标题 |
| `lines` | 对象 | 审美主线，键 `A/B/C/D`，值是定义 | 写进 md |
| `principle` | 字符串 | 体验距离原则（一句话） | 写进 md |
| `anime_watched` | 字符串数组 | **已看的番剧名**（排重，最关键） | `bangumi.seen()` |
| `anime_avoid` | 字符串数组 | 番剧排斥词（题材/手法，命中 −4 分） | `bangumi.avoid_terms()` |
| `anime_hits` | 字符串数组 | 番剧加分词（比内置表更贴个人，命中 +2） | `bangumi.hit_terms()` |
| `novels_read` | 字符串数组 | 在追的书名（排重） | `qidian.dropped()` |
| `novels_dropped` | 字符串数组 | 弃过的书名（排重） | `qidian.dropped()` |
| `novel_categories` | 字符串数组 | 偏好分类（科幻/轻小说/悬疑…）：既加权 **也决定抓哪几个榜** | `qidian.preferred_categories()`、`cards.weekly.novel_category_ids()` |
| `novel_authors` | 对象 | 认作者的加权，如 `{"远瞳": 5}` | `qidian.author_weights()` |
| `core_artists` | 字符串数组 | **内核层艺人**（唯一会推新发行的名单） | `cards.music.core_artists()` |
| `companion_artists` | 字符串数组 | 陪伴型艺人：**一票否决**，即使误写进内核层也不推 | `cards.music.core_artists()` |
| `music_avoid` | 字符串数组 | 音乐排斥（风格描述，脚本判不了，写进 md 给人和 agent 看） | 文档 |
| `game_series` | 字符串数组 | 任天堂系列命中词（如「薩爾達」） | `nintendo_hk.taste_lists()` |
| `game_hits` | 字符串数组 | 任天堂品类命中词（如「模擬」「戰棋」） | 同上 |
| `game_avoid` | 字符串数组 | 任天堂口味禁区（命中直接 drop，如「排位」） | 同上 |
| `game_caution` | 字符串数组 | 要提醒但不丢（如「恐怖」「射擊」） | 同上 |
| `voice` | 对象 | 有声内容的音色/演法口径（可选） | 写进 md |
| `notes` | 字符串 | 其它约定 | 写进 md |

**填写原则**：拿不准就留空。空 = 不筛，不会报错；编一个假的反而会污染推荐。
例外：`anime_watched` 空就是「没有已看记录」，卡片会推你看过的——这个字段宁可从访谈里
问清 / 事后用 `setup/mark.py` 补，也不要瞎填。

## profile.json（init 生成）

```json
{
  "generated_at": "2026-11-16T20:00:00",
  "name": "文杰",
  "depth": "normal",
  "lines": {"A": "...", "B": "..."},
  "anime_watched": ["..."],
  "anime_watched_all": ["...（init 自动合并的去重名单）"],
  "anime_avoid": ["..."],
  "anime_hits": ["..."],
  "novels_read": ["..."],
  "novels_dropped": ["..."],
  "novels_seen": ["...（已读 ∪ 弃书，网文排重实际用的名单）"],
  "novel_categories": ["..."],
  "novel_authors": {"远瞳": 5},
  "core_artists": ["..."],
  "companion_artists": ["..."],
  "music_avoid": ["..."],
  "game_series": [], "game_hits": [], "game_avoid": [], "game_caution": [],
  "voice": {},
  "notes": ""
}
```

## feedback.json（`setup/mark.py` 维护，不是访谈产物）

「用出来的判断」不写回 profile：重跑 `init.py` 会把档案整个覆盖，回写的东西会丢。

```json
{
  "anime": {"seen": ["葬送的芙莉莲"], "skip": ["某番"]},
  "novel": {"seen": [], "skip": ["玄鉴仙族"]},
  "album": {"seen": ["Aimer - Open α Door"], "skip": []},
  "game":  {"seen": [], "skip": []}
}
```

```bash
python3 setup/mark.py seen anime 葬送的芙莉莲     # 看过了，别再推
python3 setup/mark.py skip novel 玄鉴仙族          # 不想看
python3 setup/mark.py seen album "Aimer - Open α Door"
python3 setup/mark.py unmark anime 葬送的芙莉莲    # 标错了
python3 setup/mark.py list                        # 看现在记了什么
```

排重时 `profile.json` 与 `feedback.json` **合并生效**（`config.feedback_excludes()`）。

## 脚本怎么用它

```python
from core import config

config.profile_list("anime_watched")     # 番剧排重
config.profile_list("novels_seen")       # 网文排重
config.profile_list("core_artists")      # 音乐月报的艺人名单（空 = 这张卡不排）
config.profile_list("novel_categories")  # 分类加权 + 抓哪几个榜
config.profile_list("game_avoid")        # 任天堂禁区词
config.display_name()                    # 卡片标题里的称呼（空 = 中性标题）
config.feedback_excludes("anime")        # 回写名单（已看 ∪ 不想看）
```

没有 `profile.json` 时全部返回空列表 → 卡片仍能出，只是不筛（音乐卡会直接跳过）。
**永远不要让缺档案变成报错。**
