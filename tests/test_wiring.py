import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import main as main_mod
from optimizer import core, ctx, gpu, journal, recommend, scan, steam

ctx.set_logger(lambda m: None)


def fake_specs():
    return scan.Specs(cpu_name="Test CPU", cores=8, threads=16, ram_gb=32, ram_mhz=3600, ram_sticks=2,
                      gpus=[scan.GpuInfo("NVIDIA GeForce RTX 3080", "nvidia", "1.0", 10.0)],
                      monitors=[scan.Monitor(2560, 1440, 240, True)],
                      disks=[scan.Disk("Test NVMe", "nvme", 512.0)], os_name="Windows 11", os_build=26200)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["HO_STATE_DIR"] = str(self.tmp / "state")
        ctx.dry_run = False
        self.logs = []
        ctx.set_logger(self.logs.append)

    def tearDown(self):
        ctx.dry_run = False
        ctx.set_logger(lambda m: None)


class RunWiringTests(Base):
    def test_run_passes_tier_and_gpu_values(self):
        g = gpu.Gpu("NVIDIA GeForce RTX 3080", "nvidia", "1")
        game = steam.Game("730", "CS2", self.tmp)
        with mock.patch.object(core.games, "optimize") as opt, mock.patch.object(core.gpu, "apply_for") as ap, \
                mock.patch.object(core.steam, "steam_root", return_value=None):
            core.run(set(), [game], g, False, ["lowlat"], tier="high", gpu_values={"lowlat": 2})
        ap.assert_called_once_with(g, ["lowlat"], {"lowlat": 2})
        opt.assert_called_once_with(game, None, "high")

    def test_run_defaults_keep_old_behaviour(self):
        game = steam.Game("730", "CS2", self.tmp)
        with mock.patch.object(core.games, "optimize") as opt, mock.patch.object(core.steam, "steam_root",
                                                                               return_value=None):
            core.run(set(), [game], None, False)
        opt.assert_called_once_with(game, None, "mid")

    def test_auto_uses_plan_and_logs_notes(self):
        specs = fake_specs()
        plan = recommend.build(specs)
        game = steam.Game("730", "CS2", self.tmp)
        with mock.patch.object(core, "run") as run, mock.patch.object(core.scan_mod, "scan") as sc:
            res = core.auto(specs, [game], make_restore_point=False)
        sc.assert_not_called()
        self.assertEqual(res[0], specs)
        args, _ = run.call_args
        self.assertEqual(args[0], set(plan.tweak_ids))
        self.assertEqual(args[1], [game])
        self.assertEqual(args[2].name, "NVIDIA GeForce RTX 3080")
        self.assertFalse(args[3])
        self.assertEqual(args[4:], (plan.gpu_keys, plan.game_tier, plan.gpu_values))
        text = "\n".join(self.logs)
        self.assertIn("Скан ПК", text)
        self.assertIn(f"{specs.score}/100", text)
        for title, reason in plan.notes:
            self.assertIn(title, text)

    def test_auto_scans_when_no_specs(self):
        with mock.patch.object(core, "run"), mock.patch.object(core.scan_mod, "scan", return_value=fake_specs()) as sc:
            core.auto(None, None, make_restore_point=False)
        sc.assert_called_once()


class GpuValuesTests(Base):
    def test_build_nip_uses_given_value(self):
        s = next(x for x in gpu.NVIDIA if x.key == "fpslimit")
        self.assertIn("<SettingValue>237</SettingValue>", gpu.build_nip([(s, 237)]))

    def test_dry_run_logs_actual_value(self):
        ctx.dry_run = True
        gpu.nvidia_apply(["fpslimit", "power"], {"fpslimit": 237})
        text = "\n".join(self.logs)
        self.assertIn("237", text)
        self.assertEqual(journal.load(), [])

    def test_apply_journals_keys_and_imports_values(self):
        imported = []
        with mock.patch.object(gpu, "_import_nip", side_effect=imported.append):
            gpu.apply_for(gpu.Gpu("NVIDIA X", "nvidia", "1"), ["lowlat", "fpslimit"], {"lowlat": 2, "fpslimit": 237})
        self.assertIn("<SettingValue>237</SettingValue>", imported[0])
        self.assertIn("<SettingValue>2</SettingValue>", imported[0])
        rec = journal.load()[-1]
        self.assertEqual(rec["kind"], "nvidia")
        self.assertEqual(rec["keys"], ["lowlat", "fpslimit"])

    def test_revert_restores_defaults_for_overridden_keys(self):
        imported = []
        with mock.patch.object(gpu, "_import_nip", side_effect=imported.append):
            gpu.nvidia_apply(["lowlat"], {"lowlat": 2})
            from optimizer import revert
            revert.revert_all()
        self.assertIn("<SettingValue>0</SettingValue>", imported[-1])  # значение драйвера по умолчанию

    def test_amd_ignores_values(self):
        with mock.patch.object(gpu, "amd_apply") as amd:
            gpu.apply_for(gpu.Gpu("AMD Radeon RX 6800", "amd", "1"), ["vsync"], {"vsync": 5})
        amd.assert_called_once_with(["vsync"])

    def test_old_signatures_work(self):
        with mock.patch.object(gpu, "nvidia_apply") as na:
            gpu.apply_for(gpu.Gpu("NVIDIA X", "nvidia", "1"))
        na.assert_called_once_with(None, None)


class CliTests(Base):
    def run_main(self, *argv):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["main.py", *argv]), redirect_stdout(buf):
            main_mod.main()
        return buf.getvalue()

    def test_scan_prints_without_elevation(self):
        with mock.patch.object(main_mod.scan, "scan", return_value=fake_specs()), \
                mock.patch.object(main_mod, "is_admin", return_value=False), \
                mock.patch.object(main_mod, "elevate") as el:
            out = self.run_main("--scan")
        el.assert_not_called()
        self.assertIn("RTX 3080", out)
        self.assertIn("/100", out)
        self.assertIn("Мощный ПК", out)
        self.assertIn("Режим низкой задержки", out)

    def test_apply_all_goes_through_auto(self):
        with mock.patch.object(main_mod.core, "auto", return_value=(None, None)) as au, \
                mock.patch.object(main_mod.launchers, "all_games", return_value=[]), \
                mock.patch.object(main_mod.steam, "steam_root", return_value=None):
            self.run_main("--apply-all", "--dry-run")
        au.assert_called_once_with(None, [], make_restore_point=False)

    def test_list_uses_launchers(self):
        g = steam.Game("epic:Fortnite", "Fortnite", self.tmp)
        with mock.patch.object(main_mod.gpu, "detect", return_value=[]), \
                mock.patch.object(main_mod.steam, "steam_root", return_value=None), \
                mock.patch.object(main_mod.launchers, "all_games", return_value=[g]):
            out = self.run_main("--list")
        self.assertIn("epic:Fortnite", out)


if __name__ == "__main__":
    unittest.main()
