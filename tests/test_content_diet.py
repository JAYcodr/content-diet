"""content-diet 的离线测试：不连网、不花钱、不碰真实状态目录。

跑法::

    python3 -m unittest discover -s tests -v

每个用例都自己写 profile.json / feedback.json / seen.json，验证「档案真的驱动筛选」、
「失败真的非 0 退出」、「同一份内容不会重复发」这几条 acceptance，而不是只测函数能跑。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HOME = Path(tempfile.mkdtemp(prefix="content-diet-test-"))
os.environ["CONTENT_DIET_HOME"] = str(HOME)

from core import config, feishu, sent  # noqa: E402
from cards import games, music, weekly  # noqa: E402
from setup import doctor  # noqa: E402
import setup.mark as mark  # noqa: E402
from sources import bangumi, nintendo_hk, qidian  # noqa: E402


def reset_state() -> None:
    """清掉上一条用例的档案 / 反馈 / 去重 / seen，并让各模块丢掉缓存。"""
    for name in ("profile.json", "feedback.json", "sent.json", ".env"):
        (HOME / name).unlink(missing_ok=True)
    for sub in ("nintendo", "covers", "feishu", "music", "qidian"):
        for path in (HOME / sub).glob("*"):
            path.unlink()
    for key in list(os.environ):
        if key.startswith("FEISHU_") or key in ("BGM_API_TOKEN", "QIDIAN_COOKIE", "NETEASE_COOKIE"):
            os.environ.pop(key, None)
    config.load_env(force=True)
    bangumi.refresh()
    qidian._DROPPED = None
    nintendo_hk.refresh_taste()
    weekly._REPORTED.clear()
    config._WARNED_UNWRITABLE.clear()


def write_profile(**data) -> None:
    (HOME / "profile.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    bangumi.refresh()
    qidian._DROPPED = None
    nintendo_hk.refresh_taste()


def write_feedback(**data) -> None:
    (HOME / "feedback.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class TestStateDir(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_unwritable_state_dir_warns_exactly_once(self):
        """#16：目录建不了不能一声不响，也不能每次调用都刷屏。"""
        err = io.StringIO()
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(1, "Operation not permitted")):
            with redirect_stderr(err):
                first = config.state_dir("probe-once")
                second = config.state_dir("probe-once")
        self.assertEqual(first, second)
        self.assertIn("状态目录不可写", err.getvalue())
        self.assertIn("CONTENT_DIET_HOME", err.getvalue())
        self.assertEqual(err.getvalue().count("状态目录不可写"), 1)


class TestSendCard(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_business_error_raises_instead_of_silent_success(self):
        """#8：HTTP 200 但 code != 0 不能当成功。"""
        with mock.patch.object(feishu, "token", return_value="t"), \
                mock.patch.object(feishu, "_api", return_value={"code": 230002, "msg": "bot not in chat"}):
            with self.assertRaises(RuntimeError) as ctx:
                feishu.send_card("oc_x", {"a": 1})
        self.assertIn("230002", str(ctx.exception))
        self.assertIn("机器人进群", str(ctx.exception))

    def test_success_returns_real_message_id(self):
        with mock.patch.object(feishu, "token", return_value="t"), \
                mock.patch.object(feishu, "_api",
                                  return_value={"code": 0, "data": {"message_id": "om_123"}}):
            self.assertEqual(feishu.send_card("oc_x", {"a": 1})["message_id"], "om_123")

    def test_missing_message_id_is_a_failure(self):
        with mock.patch.object(feishu, "token", return_value="t"), \
                mock.patch.object(feishu, "_api", return_value={"code": 0, "data": {}}):
            with self.assertRaises(RuntimeError):
                feishu.send_card("oc_x", {"a": 1})


class TestDedupe(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_same_period_same_content_sends_once(self):
        """#8：同周期同内容补跑两次只发一次。"""
        write_profile(anime_watched=[], novels_seen=[])
        anime = [{"title": "芙莉莲", "sub": "Bangumi 9.0", "note": "", "cover": None, "url": "u"}]
        novels = [{"title": "黎明之剑", "sub": "远瞳 · 科幻", "note": "", "cover": None, "url": "u"}]
        calls = []

        def fake_send(chat, card):
            calls.append(chat)
            return {"message_id": "om_once"}

        err = io.StringIO()
        with mock.patch.object(weekly, "anime_rows", return_value=anime), \
                mock.patch.object(weekly, "novel_rows", return_value=novels), \
                mock.patch.object(weekly, "send_card", side_effect=fake_send), \
                mock.patch.object(sys, "argv", ["weekly", "--chat", "oc_test"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(weekly.main(), 0)
                self.assertEqual(weekly.main(), 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("已经发过", err.getvalue())
        self.assertIn("om_once", err.getvalue())


class TestProfileDrivesMusic(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_empty_core_artists_never_falls_back_to_defaults(self):
        """#6：core_artists 为空就不出音乐卡，绝不出现 Aimer / 米津等默认名单。"""
        write_profile(core_artists=[], companion_artists=[])
        self.assertEqual(music.core_artists(), [])
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["music", "--preview"]):
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                self.assertEqual(music.main(), 0)
        text = out.getvalue()
        self.assertIn("core_artists 为空", text)
        for name in ("Aimer", "米津", "ヨルシカ"):
            self.assertNotIn(name, text)

    def test_companion_artists_are_vetoed(self):
        write_profile(core_artists=["Aimer", "周杰伦"], companion_artists=["周杰伦"])
        self.assertEqual(music.core_artists(), ["Aimer"])

    def test_card_title_uses_profile_name_not_hardcoded(self):
        """#6：--preview 出来的标题不含「铃」。"""
        write_profile(core_artists=["Aimer"])
        self.assertEqual(music.card_title(), "新发行")
        write_profile(core_artists=["Aimer"], name="文杰")
        self.assertEqual(music.card_title(), "文杰 · 新发行")
        self.assertNotIn("铃", music.card_title())


class TestProfileDrivesAnime(unittest.TestCase):
    def setUp(self):
        reset_state()

    def _subject(self, tags):
        return {"name_cn": "某番", "name": "some", "tags": [{"name": t} for t in tags],
                "rating": {"score": 7.0}}

    def test_anime_avoid_from_profile_changes_score(self):
        """#6：改档案里的 anime_avoid，打分随之变化（不再只靠源码常量表）。"""
        write_profile(anime_avoid=[])
        before = bangumi.score(self._subject(["後宮"]))["score"]
        write_profile(anime_avoid=["後宮"])
        after = bangumi.score(self._subject(["後宮"]))["score"]
        self.assertLess(after, before)
        self.assertEqual(after, before - 4)

    def test_anime_hits_from_profile_add_weight(self):
        write_profile(anime_hits=["吹奏乐"])
        result = bangumi.score(self._subject(["吹奏乐"]))
        self.assertTrue(any("吹奏乐" in r for r in result["reasons"]))

    def test_feedback_seen_excludes_anime(self):
        """#7：标记已看后，下次筛选不再推。"""
        write_profile()
        self.assertFalse(bangumi.seen({"name_cn": "葬送的芙莉莲", "name": "sousou"}))
        write_feedback(anime={"seen": ["葬送的芙莉莲"]})
        bangumi.refresh()
        self.assertTrue(bangumi.seen({"name_cn": "葬送的芙莉莲", "name": "sousou"}))

    def test_weekly_title_is_neutral_without_name(self):
        write_profile()
        self.assertEqual(weekly.card_title(), "本周片单")


class TestAiringAppliesScoreFloor(unittest.TestCase):
    """评分地板在 airing 模式下也要生效（此前只有 rank 分支检查）。"""

    def setUp(self):
        reset_state()
        write_profile()

    def _subject(self, sid, bgm):
        # 带一个内置命中的标签，确保 score > 0，从而能区分「被地板拦」与「被 score<=0 拦」
        return {"id": sid, "name_cn": f"测试番{sid}", "name": f"test{sid}",
                "tags": [{"name": "时间循环"}], "rating": {"score": bgm}}

    def test_airing_skips_below_floor(self):
        low, ok = self._subject(1, 5.5), self._subject(2, 7.0)
        self.assertGreater(bangumi.score(low)["score"], 0, "前提：低分作品得先能过 score>0")
        with mock.patch.object(bangumi, "search_subjects", return_value=[low, ok]):
            out = bangumi.collect("airing", None, 10)
        ids = [s["id"] for s in out["picked"]]
        self.assertNotIn(1, ids, "5.5 分不该进 airing 片单")
        self.assertIn(2, ids)

    def test_airing_keeps_unrated(self):
        """新番常常还没评分（0 分），不能因此被砍掉。"""
        unrated = self._subject(3, 0)
        with mock.patch.object(bangumi, "search_subjects", return_value=[unrated]):
            out = bangumi.collect("airing", None, 10)
        self.assertEqual([s["id"] for s in out["picked"]], [3])

    def test_rank_still_applies_floor(self):
        low = self._subject(4, 5.5)
        with mock.patch.object(bangumi, "get", return_value={"data": [low]}):
            out = bangumi.collect("rank", None, 10)
        self.assertEqual(out["picked"], [])


class TestProfileDrivesNovels(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_preferred_category_bonus(self):
        book = {"title": "某书", "author": "某人", "category": "科幻", "summary": "简介",
                "words": "100万字", "votes": "1万", "id": "1", "url": "u"}
        write_profile(novel_categories=[])
        plain = qidian.score(book)["score"]
        write_profile(novel_categories=["科幻"])
        boosted = qidian.score(book)["score"]
        self.assertEqual(boosted, plain + 2)

    def test_feedback_skip_removes_book(self):
        write_profile()
        self.assertNotIn("玄鉴仙族", qidian.dropped())
        write_feedback(novel={"skip": ["玄鉴仙族"]})
        qidian._DROPPED = None
        self.assertIn("玄鉴仙族", qidian.dropped())

    def test_novel_category_ids_map_names(self):
        write_profile(novel_categories=["科幻", "悬疑"])
        self.assertEqual(weekly.novel_category_ids(), [9, 10])
        write_profile(novel_categories=[])
        self.assertEqual(weekly.novel_category_ids(), [9, 10, 7, 5, 6, 12])


NINTENDO_ITEMS = [
    {"id": "a1", "title": "薩爾達傳說 新作", "publisher": "Nintendo", "label": "下載版",
     "date": "2026.12.01", "month": "2026年12月", "poster_url": "", "url": "u1"},
    {"id": "b1", "title": "Cheap Asset Flip", "publisher": "Red Fables", "label": "",
     "date": "", "month": "", "poster_url": "", "url": "u2"},
    {"id": "c1", "title": "名作復刻", "publisher": "Square Enix", "label": "",
     "date": "", "month": "", "poster_url": "", "url": "u3"},
]


def run_nintendo(argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(nintendo_hk, "_get", return_value=b"<html></html>"), \
            mock.patch.object(nintendo_hk, "parse", return_value=[dict(i) for i in NINTENDO_ITEMS]), \
            mock.patch.object(sys, "argv", ["nintendo_hk"] + argv):
        with redirect_stdout(out), redirect_stderr(err):
            rc = nintendo_hk.main()
    return rc, out.getvalue(), err.getvalue()


class TestFeedbackLoop(unittest.TestCase):
    """周卡序号 → feedback.json 的写入链路（feedback.py）。"""

    def setUp(self):
        reset_state()
        write_profile()
        (HOME / "last_weekly.json").write_text(json.dumps({
            "period": "2026-W47",
            "items": [
                {"n": 1, "kind": "anime", "title": "愚者之夜", "url": "u1"},
                {"n": 2, "kind": "anime", "title": "药屋少女的呢喃 第三季", "url": "u2"},
                {"n": 3, "kind": "novel", "title": "废土边境检查官", "url": "u3"},
            ]}, ensure_ascii=False), encoding="utf-8")
        import feedback
        self.fb = feedback

    def _args(self, action, numbers=(), names=()):
        return type("A", (), {"action": action, "numbers": list(numbers), "names": list(names)})()

    def test_number_maps_to_kind_and_title(self):
        picks = self.fb.resolve(self._args("skip", ["3"]))
        self.assertEqual(picks, [("novel", "废土边境检查官")])

    def test_comma_list_and_name(self):
        self.assertEqual(len(self.fb.resolve(self._args("seen", ["1,2"]))), 2)
        # 同时给序号和名字时名字优先（resolve 里先判 names）
        self.assertEqual(self.fb.resolve(self._args("skip", ["1"], ["药屋少女"]))[0][1],
                         "药屋少女的呢喃 第三季")
        self.assertEqual(self.fb.resolve(self._args("skip", ["1"], ["愚者"]))[0][1], "愚者之夜")

    def test_bad_number_fails_loudly(self):
        with self.assertRaises(SystemExit):
            self.fb.resolve(self._args("skip", ["9"]))

    def test_apply_dedupes_and_flips_sides(self):
        self.fb.apply("skip", [("anime", "愚者之夜")])
        self.fb.apply("skip", [("anime", "愚者之夜")])          # 重复不写第二遍
        self.fb.apply("seen", [("anime", "愚者之夜")])          # 换边摘掉旧记录
        data = config.load_feedback()
        self.assertEqual(data["anime"]["skip"], [])
        self.assertEqual(data["anime"]["seen"], ["愚者之夜"])

    def test_feedback_actually_filters(self):
        """写进 skip 之后，筛选真的把它排除掉——这条才是闭环的意义。"""
        config.save_feedback({"anime": {"skip": ["愚者之夜"]}})
        bangumi.refresh()
        self.assertTrue(bangumi.seen({"name_cn": "愚者之夜", "name": "x"}))


class TestNintendoContract(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_new_payload_has_games_key_and_card_reads_it(self):
        """#10：nintendo_hk --new 的 JSON 能被 cards.games 直接读。"""
        write_profile()
        rc, out, _ = run_nintendo(["--new", "--no-posters"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("games", payload)
        self.assertEqual(payload["games"], payload["items"])
        self.assertTrue(payload["games"])
        card = games.build_card(payload)
        self.assertEqual(card["schema"], "2.0")
        titles = json.dumps(card, ensure_ascii=False)
        self.assertIn("薩爾達", titles)

    def test_payload_excludes_dropped_entries(self):
        """drop 只用于记 seen，不进 payload——否则黑名单游戏会出现在卡片里。"""
        write_profile()
        rc, out, _ = run_nintendo(["--new", "--no-posters"])
        payload = json.loads(out)
        self.assertNotIn("drop", {g["verdict"] for g in payload["games"]})
        self.assertNotIn("b1", [g["id"] for g in payload["games"]])

    def test_cards_games_also_reads_legacy_items(self):
        card = games.build_card({"items": [dict(NINTENDO_ITEMS[0])]})
        self.assertIn("薩爾達", json.dumps(card, ensure_ascii=False))

    def test_commit_all_is_rejected(self):
        """#10：--commit --all 会把没发出去的标成已见，必须被挡住。"""
        write_profile()
        rc, _, err = run_nintendo(["--commit", "--all"])
        self.assertEqual(rc, 2)
        self.assertIn("不再接受 --all", err)

    def test_commit_from_payload_only_records_sent_and_drops(self):
        """#10：白名单 keep 但没发出去的（a1）不进 seen；payload 里的 c1 与 drop 的 b1 进。"""
        write_profile()
        run_nintendo(["--new", "--no-posters"])
        payload_path = HOME / "payload.json"
        payload_path.write_text(json.dumps({"games": [{"id": "c1"}]}), encoding="utf-8")
        rc, out, _ = run_nintendo(["--commit", "--from-payload", str(payload_path)])
        self.assertEqual(rc, 0)
        seen = json.loads((HOME / "nintendo" / "seen.json").read_text(encoding="utf-8"))
        self.assertIn("c1", seen["ids"])
        self.assertIn("b1", seen["ids"])
        self.assertNotIn("a1", seen["ids"])
        self.assertIn("已记入 seen", out)

    def test_commit_without_pending_fails_loudly(self):
        write_profile()
        rc, _, err = run_nintendo(["--commit"])
        self.assertEqual(rc, 2)
        self.assertIn("没有可提交的记录", err)

    def test_profile_game_avoid_changes_verdict(self):
        """#6：改档案里的 game_avoid，命中/禁区结果随之变化。"""
        item = {"id": "d1", "title": "Some Roguelike", "publisher": "Indie", "label": "",
                "date": "", "month": "", "poster_url": "", "url": "u"}
        write_profile(game_avoid=[])
        self.assertNotEqual(nintendo_hk.taste(item)["taste"], "avoid")
        write_profile(game_avoid=["roguelike"])
        self.assertEqual(nintendo_hk.taste(item)["taste"], "avoid")


class TestDoctor(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_unwired_token_is_not_reported_as_configured(self):
        """#9：BGM_API_TOKEN 填了也不算「已配」，因为代码还没读它。"""
        os.environ["BGM_API_TOKEN"] = "x" * 32
        config.load_env(force=True)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["doctor", "--json"]), \
                mock.patch.object(doctor, "probe", return_value=(True, "HTTP 200（直连）")):
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                self.assertEqual(doctor.main(), 0)
        payload = json.loads(out.getvalue())
        entry = next(t for t in payload["tokens"] if t["key"] == "BGM_API_TOKEN")
        self.assertTrue(entry["set"])
        self.assertFalse(entry["effective"])
        self.assertFalse(entry["wired"])
        qidian_entry = next(t for t in payload["tokens"] if t["key"] == "QIDIAN_COOKIE")
        self.assertFalse(qidian_entry["wired"])

    def test_card_ready_requires_reachable_sources(self):
        """#12：能力矩阵不能只看飞书凭据在不在，还要看数据源可达性。"""
        os.environ.update({"FEISHU_APP_ID": "cli_x", "FEISHU_APP_SECRET": "s" * 32,
                           "FEISHU_CHAT_ID": "oc_x"})
        config.load_env(force=True)
        matrix = doctor.capability_matrix({"Bangumi": False, "起点（移动端）": True,
                                           "网易云音乐": True, "任天堂香港": True},
                                          {"feishu": True})
        weekly_card = next(c for c in matrix if c["card"].startswith("片单卡"))
        self.assertFalse(weekly_card["ready"])

    def test_send_test_reports_failure_without_crashing(self):
        os.environ.update({"FEISHU_APP_ID": "cli_x", "FEISHU_APP_SECRET": "s" * 32,
                           "FEISHU_CHAT_ID": "oc_x"})
        config.load_env(force=True)
        with mock.patch.object(feishu, "token", return_value="t"), \
                mock.patch.object(feishu, "_api", return_value={"code": 230002, "msg": "bot not in chat"}):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = doctor.send_test()
        self.assertEqual(rc, 1)
        self.assertIn("发送失败", out.getvalue())
        self.assertIn("机器人有没有被拉进那个群", out.getvalue())


class TestMark(unittest.TestCase):
    def setUp(self):
        reset_state()

    def _run(self, argv):
        with mock.patch.object(sys, "argv", ["mark"] + argv):
            with redirect_stdout(io.StringIO()):
                return mark.main()

    def test_mark_seen_persists_and_filters(self):
        """#7：回写落在文件里，重新读也生效（不依赖进程内存）。"""
        write_profile()
        self.assertEqual(self._run(["seen", "anime", "葬送的芙莉莲"]), 0)
        saved = json.loads((HOME / "feedback.json").read_text(encoding="utf-8"))
        self.assertIn("葬送的芙莉莲", saved["anime"]["seen"])
        bangumi.refresh()
        self.assertTrue(bangumi.seen({"name_cn": "葬送的芙莉莲", "name": "x"}))

    def test_unmark_removes(self):
        write_profile()
        self._run(["skip", "novel", "玄鉴仙族"])
        self.assertEqual(self._run(["unmark", "novel", "玄鉴仙族"]), 0)
        qidian._DROPPED = None
        self.assertNotIn("玄鉴仙族", qidian.dropped())

    def test_album_feedback_excludes_music(self):
        write_profile(core_artists=["Aimer"])
        self._run(["seen", "album", "Aimer - Open α Door"])
        album = {"id": 1, "name": "Open α Door", "artist": "Aimer", "cover_url": "", "date": "2026-11",
                 "tracks": 10, "url": "u"}
        self.assertTrue(music.album_excluded(album))
        other = {**album, "name": "别的专辑"}
        self.assertFalse(music.album_excluded(other))


class TestFeishuFromDsh(unittest.TestCase):
    def setUp(self):
        reset_state()
        import setup.feishu_from_dsh_im as dsh
        self.dsh = dsh
        self.tmp = Path(tempfile.mkdtemp(prefix="dsh-"))

    def test_reads_bots_list_and_exact_secret_ref(self):
        """#13：appId 在 bots[] 里，secret 按 secretRef 精确取——不能拿 refs 第一条。"""
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"version": 2, "bots": [
            {"id": "bot_1", "appId": "cli_aaa", "secretRef": "DSH_FEISHU_APP_SECRET_1", "activated": 0},
            {"id": "bot_2", "appId": "cli_bbb", "secretRef": "DSH_FEISHU_APP_SECRET_2", "activated": 2},
        ]}), encoding="utf-8")
        cred = self.tmp / ".credentials.yaml"
        cred.write_text("refs:\n  XIAOMI_API_KEY: " + "k" * 51 + "\n"
                        "  DSH_FEISHU_APP_SECRET_2: " + "s" * 32 + "\n", encoding="utf-8")
        bots = self.dsh.read_bots(cfg)
        bot = self.dsh.pick_bot(bots)
        self.assertEqual(bot["appId"], "cli_bbb")          # activated 的优先
        self.assertEqual(bot["secretRef"], "DSH_FEISHU_APP_SECRET_2")
        refs = self.dsh.read_refs(cred)
        secret, how = self.dsh.resolve_secret(refs, bot["secretRef"])
        self.assertEqual(secret, "s" * 32)
        self.assertNotEqual(secret, "k" * 51)
        self.assertIn("DSH_FEISHU_APP_SECRET_2", how)

    def test_multiple_candidates_without_ref_is_refused(self):
        cred = self.tmp / ".credentials.yaml"
        cred.write_text("refs:\n  FEISHU_APP_SECRET_A: " + "a" * 32 + "\n  FEISHU_APP_SECRET_B: "
                        + "b" * 32 + "\n", encoding="utf-8")
        refs = self.dsh.read_refs(cred)
        secret, _ = self.dsh.resolve_secret(refs, "")
        self.assertEqual(secret, "")

    def test_secret_equal_to_app_id_exits(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"appId": "cli_same", "secretRef": "K"}), encoding="utf-8")
        cred = self.tmp / ".credentials.yaml"
        cred.write_text("refs:\n  K: cli_same\n", encoding="utf-8")
        with mock.patch.object(self.dsh, "first_existing",
                               side_effect=lambda key: cfg if key == "integration_config" else cred), \
                mock.patch.object(sys, "argv", ["x"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(self.dsh.main(), 1)

    def test_short_secret_is_refused(self):
        """不是「读到 32 个字符」就算过：太短的 key 直接挡在写 .env 之前。"""
        self.assertTrue(self.dsh.sanity_check("cli_x", "shortkey"))
        self.assertTrue(self.dsh.sanity_check("cli_x", "cli_x"))
        self.assertEqual(self.dsh.sanity_check("cli_x", "s" * 32), "")


class TestSentState(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_fingerprint_stable_and_period_keyed(self):
        a = sent.fingerprint(["x"], ["y"])
        self.assertEqual(a, sent.fingerprint(["x"], ["y"]))
        self.assertNotEqual(a, sent.fingerprint(["x"], ["z"]))
        key = sent.week_key("weekly")
        self.assertRegex(key, r"^weekly-\d{4}-W\d{2}$")
        self.assertIsNone(sent.already_sent(key, a))
        sent.mark_sent(key, a, "om_9")
        self.assertEqual(sent.already_sent(key, a), "om_9")
        self.assertIsNone(sent.already_sent(key, "other"))


if __name__ == "__main__":
    unittest.main()
