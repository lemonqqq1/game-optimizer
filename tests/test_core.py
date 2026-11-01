import os
import tempfile
import unittest
import winreg
from pathlib import Path

from optimizer import ctx, games, journal, registry as reg, revert, steam, vdf

ctx.set_logger(lambda m: None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["HO_STATE_DIR"] = str(self.tmp / "state")
        ctx.dry_run = False


class VdfTests(unittest.TestCase):
    def test_roundtrip_and_case(self):
        d = {"UserLocalConfigStore": {"software": {"Path": "C:\\Games"}}}
        text = vdf.dump(d)
        self.assertIn("C:\\\\Games", text)
        back = vdf.parse(text)
        self.assertEqual(back, d)
        self.assertEqual(vdf.get_ci(vdf.get_ci(back, "UserLocalConfigStore"), "Software")["Path"], "C:\\Games")

    def test_merge_flags_keeps_user_choice(self):
        self.assertEqual(steam.merge_flags("-novid -w", ["-novid", "-high", "+fps_max 0"]),
                         "-novid -w -high +fps_max 0")
        self.assertEqual(steam.merge_flags("", ["-high"]), "-high")


class FileTests(Base):
    def test_kv_patch_only_existing_keys_and_revert(self):
        f = self.tmp / "video.txt"
        f.write_text('"setting.mat_vsync"\t\t"1"\n"other"\t\t"5"\n', "utf-8")
        changed = games.patch_kv(f, {"setting.mat_vsync": "0", "setting.absent": "1"})
        self.assertEqual(changed, ["setting.mat_vsync"])
        self.assertIn('"0"', f.read_text("utf-8"))
        self.assertNotIn("absent", f.read_text("utf-8"))
        revert.revert_all()
        self.assertIn('"setting.mat_vsync"\t\t"1"', f.read_text("utf-8"))

    def test_autoexec_block_idempotent_and_revert(self):
        f = self.tmp / "cfg" / "autoexec.cfg"
        games.write_block(f, ['fps_max "0"'])
        games.write_block(f, ['fps_max "0"'])
        self.assertEqual(f.read_text("utf-8").count(games.BEGIN), 1)
        revert.revert_all()
        self.assertFalse(f.exists())

    def test_dry_run_changes_nothing(self):
        f = self.tmp / "video.txt"
        f.write_text('"setting.mat_vsync"\t\t"1"\n', "utf-8")
        ctx.dry_run = True
        games.patch_kv(f, {"setting.mat_vsync": "0"})
        games.write_block(self.tmp / "a.cfg", ["x"])
        self.assertIn('"1"', f.read_text("utf-8"))
        self.assertFalse((self.tmp / "a.cfg").exists())
        self.assertEqual(journal.load(), [])

    def test_exe_picker_skips_installers(self):
        g = steam.Game("1", "X", self.tmp)
        (self.tmp / "UbisoftConnectInstaller.exe").write_bytes(b"0" * 500)
        (self.tmp / "FC3Editor.exe").write_bytes(b"0" * 400)
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "game.exe").write_bytes(b"0" * 100)
        self.assertEqual(games.find_exe(g, None).name, "game.exe")


class LaunchOptionsTests(Base):
    def test_set_launch_options_and_revert(self):
        cfg = self.tmp / "userdata" / "1" / "config" / "localconfig.vdf"
        cfg.parent.mkdir(parents=True)
        src = vdf.dump({"UserLocalConfigStore": {"Software": {"Valve": {"Steam": {
            "apps": {"730": {"LaunchOptions": "-novid -w"}}}}}}})
        cfg.write_text(src, "utf-8")
        orig = steam.is_steam_running
        steam.is_steam_running = lambda: False
        try:
            self.assertTrue(steam.set_launch_options(self.tmp, "730", ["-novid", "-high"]))
        finally:
            steam.is_steam_running = orig
        d = vdf.parse(cfg.read_text("utf-8"))
        app = d["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["730"]
        self.assertEqual(app["LaunchOptions"], "-novid -w -high")
        revert.revert_all()
        self.assertEqual(cfg.read_text("utf-8"), src)

    def test_refuses_while_steam_running(self):
        cfg = self.tmp / "userdata" / "1" / "config" / "localconfig.vdf"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(vdf.dump({"UserLocalConfigStore": {}}), "utf-8")
        orig = steam.is_steam_running
        steam.is_steam_running = lambda: True
        try:
            with self.assertRaises(steam.SteamRunning):
                steam.set_launch_options(self.tmp, "730", ["-high"])
        finally:
            steam.is_steam_running = orig


class GpuTests(Base):
    def test_nip_contains_chosen_settings(self):
        from optimizer import gpu
        chosen = [s for s in gpu.NVIDIA if s.key in ("power", "vsync")]
        text = gpu.build_nip([(s, s.value) for s in chosen])
        self.assertIn("<SettingID>274197361</SettingID>", text)
        self.assertIn("<SettingValue>138504007</SettingValue>", text)
        self.assertEqual(text.count("<ProfileSetting>"), 2)

    def test_amd_strings_are_utf16(self):
        from optimizer import gpu
        vs = next(s for s in gpu.AMD if s.key == "vsync")
        self.assertEqual(vs.reg[2], b"0\x00")


class RegistryTests(Base):
    PATH = r"Software\GameOptimizerTest"

    def tearDown(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.PATH)
        except OSError:
            pass

    def test_write_revert_new_and_existing(self):
        reg.write("HKCU", self.PATH, "A", 5)
        reg.write("HKCU", self.PATH, "A", 7)
        reg.write("HKCU", self.PATH, "B", b"0\x00", winreg.REG_BINARY)
        self.assertEqual(reg.read("HKCU", self.PATH, "A")[0], 7)
        revert.revert_all()
        self.assertIsNone(reg.read("HKCU", self.PATH, "A"))
        self.assertIsNone(reg.read("HKCU", self.PATH, "B"))

    def test_revert_restores_old_value(self):
        reg.write("HKCU", self.PATH, "A", 1)
        journal.clear()
        reg.write("HKCU", self.PATH, "A", 9)
        revert.revert_all()
        self.assertEqual(reg.read("HKCU", self.PATH, "A")[0], 1)


if __name__ == "__main__":
    unittest.main()
