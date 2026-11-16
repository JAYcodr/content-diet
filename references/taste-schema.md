# 档案字段说明

两样东西：

- `answers.json`：**你（agent）从访谈里整理出来的原始答案**，喂给 `setup/init.py`
- `profile.json` + `taste_profile.md`：**init 生成的档案**，脚本和卡片读这个

## answers.json

| 字段 | 类型 | 说明 | 空值的后果 |
|---|---|---|---|
| `depth` | `skip`/`rough`/`normal`/`detailed` | 访谈深度，只记录用 | 无影响 |
| `lines` | 对象 | 审美主线，键是 `A/B/C/D`，值是定义 | 卡片按通用口味排序 |
| `principle` | 字符串 | 体验距离原则（一句话） | 写进 md 的"未填" |
| `anime_watched` | 字符串数组 | **已看的番剧名**（排重用，最关键的字段） | 会推已看过的 |
| `anime_avoid` | 字符串数组 | 排斥信号（题材/手法，不是具体作品） | 不筛 |
| `novels_read` | 字符串数组 | 在追的书名 | 会推正在追的 |
| `novels_dropped` | 字符串数组 | 弃过的书名 | 可能重复推 |
| `novel_categories` | 字符串数组 | 偏好分类（科幻/轻小说/历史…） | 不做分类加权 |
| `core_artists` | 字符串数组 | **内核层艺人**（会推新发行） | 不排音乐月报 |
| `companion_artists` | 字符串数组 | 陪伴型艺人（**永不推**） | 无影响（本来就不在这批里） |
| `music_avoid` | 字符串数组 | 音乐排斥（电音 drop、偶像团…） | 不筛 |
| `voice` | 对象 | 有声内容的音色/演法口径（可选） | 写进 md 的备注 |
| `notes` | 字符串 | 其它约定（比如"旁白不要给表演指令"） | 无 |

**填写原则**：拿不准就留空。空 = 不筛，不会报错；编一个假的反而会污染推荐。

## profile.json（init 生成）

```json
{
  "generated_at": "2026-11-16T20:00:00",
  "depth": "normal",
  "lines": {"A": "...", "B": "..."},
  "anime_watched": ["..."],
  "anime_avoid": ["..."],
  "novels_read": ["..."],
  "novels_dropped": ["..."],
  "novels_seen": ["...（已读 ∪ 弃书，脚本实际用的排重名单）"],
  "novel_categories": ["..."],
  "core_artists": ["..."],
  "companion_artists": ["..."],
  "music_avoid": ["..."],
  "voice": {},
  "notes": ""
}
```

`anime_watched_all` / `novels_seen` 是 init 自动算的合并名单，脚本只需要读这两个就够。

## 脚本怎么用它

```python
from core import config

config.profile_list("anime_watched")   # 番剧排重
config.profile_list("novels_seen")     # 网文排重
config.profile_list("core_artists")    # 音乐月报的艺人清单（空则用内置默认）
config.profile_list("novel_categories")  # 分类加权
```

没有 `profile.json` 时全部返回空列表 → 卡片仍能出，只是不筛。**永远不要让缺档案变成报错。**
