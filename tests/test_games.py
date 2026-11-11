import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from optimizer import ctx, games, journal, launchers, revert, steam

ctx.set_logger(lambda m: None)

INI = "[/Script/Engine.GameUserSettings]\r\nbUseVSync=True\r\nsg.TextureQuality=3\r\n\r\n[Other]\r\nsg.ShadowQuality=2\r\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["HO_STATE_DIR"] = str(self.tmp / "state")
        ctx.dry_run = False


class PatchIniTests(Base):
    def make(self, text=INI, enc="utf-8", bom=b""):
        f = self.tmp / "GameUserSettings.ini"
        f.write_bytes(bom + text.encode(enc))
        return f

    def test_changes_existing_and_ignores_missing(self):
        f = self.make()
        ch = games.patch_ini(f, {(None, "bUseVSync"): "False", (None, "sg.Absent"): "1",
                                 ("NoSuchSection", "sg.TextureQuality"): "0"})
        self.assertEqual(ch, ["bUseVSync"])
        txt = f.read_bytes().decode("utf-8")
        self.assertIn("bUseVSync=False\r\n", txt)
        self.assertNotIn("Absent", txt)
        self.assertIn("sg.TextureQuality=3", txt)

    def test_section_respected(self):
        f = self.make()
        games.patch_ini(f, {("Other", "sg.ShadowQuality"): "0", ("/Script/Engine.GameUserSettings", "sg.ShadowQuality"): "1"})
        self.assertIn("[Other]\r\nsg.ShadowQuality=0", f.read_bytes().decode("utf-8"))

    def test_preserves_crlf_and_other_lines(self):
        f = self.make()
        games.patch_ini(f, {(None, "sg.TextureQuality"): "0"})
        self.assertEqual(f.read_bytes().decode("utf-8"), INI.replace("TextureQuality=3", "TextureQuality=0"))

    def test_utf16_roundtrip(self):
        f = self.make(enc="utf-16-le", bom=b"\xff\xfe")
        self.assertEqual(games.patch_ini(f, {(None, "bUseVSync"): "False"}), ["bUseVSync"])
        raw = f.read_bytes()
        self.assertTrue(raw.startswith(b"\xff\xfe"))
        self.assertEqual(raw[2:].decode("utf-16-le"), INI.replace("bUseVSync=True", "bUseVSync=False"))

    def test_dry_run_writes_nothing(self):
        f = self.make()
        ctx.dry_run = True
        self.assertEqual(games.patch_ini(f, {(None, "bUseVSync"): "False"}), ["bUseVSync"])
        self.assertEqual(f.read_bytes().decode("utf-8"), INI)
        self.assertEqual(journal.load(), [])

    def test_backup_in_journal_and_revert(self):
        f = self.make()
        games.patch_ini(f, {(None, "bUseVSync"): "False"})
        self.assertEqual([e["path"] for e in journal.load()], [str(f)])
        revert.revert_all()
        self.assertEqual(f.read_bytes().decode("utf-8"), INI)

    def test_read_only_skipped(self):
        f = self.make()
        os.chmod(f, stat.S_IREAD)
        try:
            self.assertEqual(games.patch_ini(f, {(None, "bUseVSync"): "False"}), [])
            self.assertEqual(f.read_bytes().decode("utf-8"), INI)
            self.assertFalse(os.access(f, os.W_OK))      # атрибут не сбрасывали
        finally:
            os.chmod(f, stat.S_IWRITE)

    def test_missing_file(self):
        self.assertEqual(games.patch_ini(self.tmp / "none.ini", {(None, "a"): "1"}), [])


class SpecTests(Base):
    def test_prefixes(self):
        loc, saved, docs = self.tmp / "L", self.tmp / "H", self.tmp / "D"
        for base, rel in ((loc, "Game/A/x.ini"), (saved / "Saved Games", "Respawn/v.txt"), (docs, "My/c.ini")):
            (base / rel).parent.mkdir(parents=True)
            (base / rel).write_text("x")
        (loc / "Game/B").mkdir()
        (loc / "Game/B/x.ini").write_text("x")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(loc)}), \
                mock.patch("pathlib.Path.home", return_value=saved), \
                mock.patch.object(games.reg, "read", return_value=(str(docs), 2)):
            self.assertEqual(len(games.resolve_spec(r"local:Game\*\x.ini")), 2)
            self.assertEqual(games.resolve_spec("saved:Respawn/v.txt"), [saved / "Saved Games" / "Respawn" / "v.txt"])
            self.assertEqual(games.resolve_spec("docs:My/c.ini"), [docs / "My" / "c.ini"])
        with mock.patch.object(games.reg, "read", return_value=None), \
                mock.patch("pathlib.Path.home", return_value=saved):
            self.assertEqual(games._documents(), saved / "Documents")

    def test_userdata_game_and_absolute(self):
        f = self.tmp / "userdata" / "123" / "730" / "a.txt"
        f.parent.mkdir(parents=True)
        f.write_text("x")
        self.assertEqual(games.resolve_spec("userdata:730/a.txt", self.tmp), [f])
        self.assertEqual(games.resolve_spec("userdata:730/a.txt", None), [])
        (self.tmp / "g").mkdir()
        (self.tmp / "g" / "v.txt").write_text("x")
        self.assertEqual(games.resolve_spec("game:v.txt", None, self.tmp / "g"), [self.tmp / "g" / "v.txt"])
        self.assertEqual(games.resolve_spec(str(f)), [f])


class TierTests(Base):
    def test_low_and_high_differ(self):
        for pid in ("730", "578080", "epic:Fortnite", "1172470"):
            p = games.PROFILES[pid]
            self.assertNotEqual(p.video["low"], p.video["high"], pid)

    def test_vsync_off_everywhere(self):
        for pid, p in games.PROFILES.items():
            for spec, upd in list(p.kv_files) + [x for t in p.video.values() for x in t]:
                for k, v in upd.items():
                    name = k if isinstance(k, str) else k[1]
                    if "vsync" in name.lower():
                        self.assertIn(v, ("0", "False"), f"{pid} {name}")
            specs = [(t, upd) for t in games.TIERS for _, upd in p.video.get(t, [])]
            for t, upd in specs:   # в каждом уровне, где есть ini/vsync-ключ, v-sync выключен
                if any(not isinstance(k, str) for k in upd):
                    self.assertIn((None, "bUseVSync"), upd, f"{pid} {t}")

    def test_optimize_applies_tier(self):
        gdir = self.tmp / "Fortnite"
        gdir.mkdir()
        loc = self.tmp / "L"
        ini = loc / "FortniteGame/Saved/Config/WindowsClient/GameUserSettings.ini"
        ini.parent.mkdir(parents=True)
        ini.write_text("[S]\nbUseVSync=True\nsg.TextureQuality=3\nsg.ShadowQuality=3\n", "utf-8")
        g = steam.Game("epic:Fortnite", "Fortnite", gdir)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(loc)}), mock.patch.object(games, "exe_tweaks"), \
                mock.patch.object(steam, "set_launch_options") as slo:
            games.optimize(g, None, "low")
            low = ini.read_text("utf-8")
            ini.write_text("[S]\nbUseVSync=True\nsg.TextureQuality=0\nsg.ShadowQuality=3\n", "utf-8")
            games.optimize(g, None, "high")
            high = ini.read_text("utf-8")
            slo.assert_not_called()                      # не числовой appid: параметры запуска Steam не трогаем
        self.assertIn("sg.TextureQuality=0", low)
        self.assertIn("sg.TextureQuality=2", high)
        self.assertIn("bUseVSync=False", low + high)

    def test_two_positional_args_and_numeric_launch(self):
        gdir = self.tmp / "game"
        gdir.mkdir()
        g = steam.Game("730", "CS2", gdir)
        with mock.patch.object(games, "exe_tweaks"), mock.patch.object(steam, "set_launch_options") as slo:
            games.optimize(g, self.tmp)
            slo.assert_called_once()

    def test_no_exe_tweaks_flag(self):
        gdir = self.tmp / "val"
        gdir.mkdir()
        (gdir / "x.exe").write_bytes(b"0" * 10)
        g = steam.Game("riot:valorant", "VALORANT", gdir)
        with mock.patch.object(games, "exe_tweaks") as et:
            games.optimize(g, None, "mid")
            et.assert_not_called()


class SupportedTests(unittest.TestCase):
    def test_lists_every_profile(self):
        sup = dict(games.supported())
        self.assertEqual(set(sup), set(games.PROFILES))
        self.assertTrue(all(sup.values()))
        for pid in ("730", "570", "1172470", "578080", "252490", "epic:Fortnite", "riot:valorant"):
            self.assertIn(pid, sup)


class EpicTests(Base):
    def write(self, name, data, raw=None):
        d = self.tmp / "m"
        d.mkdir(exist_ok=True)
        (d / name).write_text(raw if raw is not None else json.dumps(data), "utf-8")
        return d

    def test_epic_games_filtering(self):
        ok = self.tmp / "Fortnite"
        ok.mkdir()
        ue = self.tmp / "UE"
        ue.mkdir()
        inc = self.tmp / "Inc"
        inc.mkdir()
        self.write("a.item", {"DisplayName": "Fortnite", "InstallLocation": str(ok), "AppName": "Fortnite",
                              "LaunchExecutable": r"FortniteGame\Binaries\Win64\FortniteLauncher.exe",
                              "bIsIncompleteInstall": False, "AppCategories": ["public", "games", "applications"]})
        self.write("b.item", {"DisplayName": "Half", "InstallLocation": str(inc), "AppName": "Half",
                              "bIsIncompleteInstall": True})
        self.write("c.item", {"DisplayName": "Gone", "InstallLocation": str(self.tmp / "nope"), "AppName": "Gone"})
        self.write("d.item", None, raw="{ not json")
        self.write("e.item", {"DisplayName": "Unreal Engine", "InstallLocation": str(ue), "AppName": "UE_5.3"})
        self.write("f.item", {"DisplayName": "Plug", "InstallLocation": str(ue), "AppName": "Plug",
                              "AppCategories": ["plugins", "plugins/engine"]})
        self.write("g.item", [1, 2])
        res = launchers.epic_games(self.tmp / "m")
        self.assertEqual([(g.appid, g.name, g.path) for g in res], [("epic:Fortnite", "Fortnite", ok)])
        self.assertIn("FortniteLauncher.exe", launchers.EXECUTABLES["epic:Fortnite"])

    def test_missing_dir_and_all_games(self):
        self.assertEqual(launchers.epic_games(self.tmp / "absent"), [])
        with mock.patch.object(launchers, "epic_games", return_value=[steam.Game("epic:B", "b", self.tmp)]):
            res = launchers.all_games(None)
            self.assertEqual([g.appid for g in res], ["epic:B"])
            with mock.patch.object(steam, "installed_games", return_value=[steam.Game("1", "A", self.tmp)]):
                self.assertEqual([g.name for g in launchers.all_games(self.tmp)], ["A", "b"])

    def test_find_exe_uses_manifest(self):
        gdir = self.tmp / "G"
        (gdir / "bin").mkdir(parents=True)
        (gdir / "bin" / "run.exe").write_bytes(b"0")
        (gdir / "big.exe").write_bytes(b"0" * 100)
        launchers.EXECUTABLES["epic:G"] = r"bin\run.exe"
        try:
            self.assertEqual(games.find_exe(steam.Game("epic:G", "G", gdir), None).name, "run.exe")
        finally:
            launchers.EXECUTABLES.pop("epic:G", None)


if __name__ == "__main__":
    unittest.main()
