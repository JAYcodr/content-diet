# content-diet 一周推进方案（2026-11-19 ~ 11-25）

## 一、现状：评分地板只在 rank 模式生效

`cards/weekly.py:110` 每周卡取番剧用的是 `anime_pick.collect("airing", None, limit)`，
而质量地板只写在 rank 分支里：`sources/bangumi.py:233`

```python
if mode == "rank" and result["bgm_score"] and result["bgm_score"] < MIN_BGM_SCORE:
```

`MIN_BGM_SCORE = 6.2`（`sources/bangumi.py:75`）。模块 docstring 承诺「Bangumi 评分作为质量地板，低于阈值不推」，
实际只在 rank 模式兑现；airing 模式只要标签命中、总分为正就进卡。

实测（2026-11-18，本季 airing，limit=12）：`赛博朋克：边缘行者 2` 的 Bangumi 评分 **5.5** 仍在榜，
另有 6.3 / 6.4 两条也在 6.2 之下。`bgm_score and` 那半段是对的——新番没评分时不该被误杀——
错的是把「没评分」和「有低分」混成同一条短路。

影响面：每周发给用户的片单卡会自动带上低分新番，「按口味筛」的承诺被质量端漏水稀释。

## 二、方案（本周三件）

1. **修地板**（11-19，owner：mac 会话 / 或 hamelin 手工）
   把条件拆成「有评分且低于地板 → 剔」，去掉 `mode == "rank"` 限制；`bgm_score == 0`（无评分）继续放行。
   产出：`sources/bangumi.py` 一处条件修改 + commit。

2. **补回归用例**（11-19，同上）
   `tests/test_content_diet.py` 增加一条：构造 `rating.score=5.5` 且标签命中的 subject，
   走 `collect("airing")` 断言不进 `picked`；再造一条 `rating` 缺失的，断言仍能进。
   产出：用例通过，`python3 -m unittest discover -s tests` 全绿。

3. **观察一期**（11-26，owner：hamelin）
   看 11-25 那期卡面：还剩几条 < 6.2、有没有误杀没评分的新番。产出：一句结论回 agent-hub。

## 三、本周不做

- **不做** `search_subjects` 的 `/calendar` 回退：docstring（`sources/bangumi.py:113`）写了「失败再退回 /calendar」，
  实现里没有。但本周没有真实失败样本，改完也无法验收，留到下周或等一次真故障。
- **不碰** `sources/nintendo_hk.py` 的「资产翻新 / AI 图小作」启发式：规则靠人肉判断，离线测不出对错，
  改了只会把「看起来合理」当验证。
- **不动** 飞书卡片视觉与 `core/sent.py` 去重逻辑：与本周目标无关，改动面大且需要真发才能验。

> 800 字内已收敛；若只做一件，做第 1 件。
