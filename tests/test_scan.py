import unittest
from unittest import mock

from optimizer import ctx, gpu, recommend, scan, system_tweaks
from optimizer.scan import Disk, GpuInfo, Monitor, Specs

ctx.set_logger(lambda m: None)

GB = 1024 ** 3
MON144 = [Monitor(2560, 1440, 144, True)]
MON60 = [Monitor(1920, 1080, 60, True)]


def desktop_raw():
    return {
        "cpu": [{"Name": "AMD Ryzen 7 5800X   8-Core Processor", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16}],
        "ram": [{"Capacity": 16 * GB, "Speed": 3200, "ConfiguredClockSpeed": 3200}] * 2,
        "gpu": [{"Name": "AMD Radeon(TM) Graphics", "DriverVersion": "31.0", "AdapterRAM": 536870912},
                {"Name": "NVIDIA GeForce RTX 3060", "DriverVersion": "32.0.15.6", "AdapterRAM": 4293918720}],
        "os": {"Caption": "Microsoft Windows 11 Pro", "BuildNumber": "26200"},
        "chassis": [3],
        "battery": [],
        "disks": [{"FriendlyName": "Samsung 980", "MediaType": "SSD", "BusType": "NVMe", "Size": 1000204886016},
                  {"FriendlyName": "WD Blue", "MediaType": "HDD", "BusType": "SATA", "Size": 2000398934016}],
        "sysfree": 300 * GB,
    }


def laptop_raw():
    return {
        "cpu": {"Name": "Intel(R) Core(TM) i5-10300H", "NumberOfCores": 4, "NumberOfLogicalProcessors": 8},
        "ram": {"Capacity": 8 * GB, "Speed": 2666, "ConfiguredClockSpeed": None},
        "gpu": [{"Name": "Intel(R) UHD Graphics", "DriverVersion": "30.0", "AdapterRAM": 1073741824},
                {"Name": "NVIDIA GeForce GTX 1650", "DriverVersion": "31.0", "AdapterRAM": 4293918720}],
        "os": {"Caption": "Microsoft Windows 10 Home", "BuildNumber": "19045"},
        "chassis": [10],
        "battery": {"Name": "Battery"},
        "disks": {"FriendlyName": "KBG30", "MediaType": "Unspecified", "BusType": "NVMe", "Size": 512110190592},
        "sysfree": 15 * GB,
    }


def nv(name="NVIDIA GeForce RTX 3060", vram=12.0):
    return GpuInfo(name, "nvidia", "1", vram)


def make(g=None, tier_threads=16, ram=32, disk="nvme", mons=MON144, laptop=False, battery=False,
         build=26200, sticks=2, mhz=3600, free=200.0):
    return Specs(cpu_name="cpu", cores=tier_threads // 2, threads=tier_threads, ram_gb=ram, ram_mhz=mhz,
                 ram_sticks=sticks, gpus=[g] if g else [], monitors=list(mons), disks=[Disk("d", disk, 500)],
                 system_free_gb=free, os_build=build, is_laptop=laptop, on_battery=battery)


class ParseTests(unittest.TestCase):
    def test_desktop(self):
        s = scan.parse(desktop_raw(), MON144, {"NVIDIA GeForce RTX 3060": 12.0}, False)
        self.assertEqual((s.cores, s.threads, s.ram_gb, s.ram_mhz, s.ram_sticks), (8, 16, 32, 3200, 2))
        self.assertEqual(s.cpu_name, "AMD Ryzen 7 5800X 8-Core Processor")
        self.assertEqual(s.gpu.name, "NVIDIA GeForce RTX 3060")
        self.assertEqual(s.gpu.vram_gb, 12.0)  # из реестра, а не обрезанные 4 ГБ
        self.assertEqual([d.kind for d in s.disks], ["nvme", "hdd"])
        self.assertEqual(s.os_build, 26200)
        self.assertEqual(s.os_name, "Windows 11 Pro")
        self.assertFalse(s.is_laptop)
        self.assertEqual(s.system_free_gb, 300.0)
        self.assertEqual(s.monitor.hz, 144)
        self.assertEqual(s.tier, "high")
        self.assertTrue(0 <= s.score <= 100)

    def test_system_disk_first_and_drive_kinds(self):
        raw = desktop_raw()
        raw["disks"][0]["DeviceId"], raw["disks"][1]["DeviceId"] = "0", "1"
        raw["parts"] = [{"DriveLetter": "C", "DiskNumber": 1}, {"DriveLetter": "D", "DiskNumber": 0}]
        raw["sysdrive"] = "C"
        s = scan.parse(raw, [], {}, False)
        self.assertEqual(s.disks[0].model, "WD Blue")
        self.assertEqual(s.system_disk_kind, "hdd")
        self.assertEqual(s.game_drive_kinds, {"C": "hdd", "D": "nvme"})

    def test_vram_fallback_adapter_ram(self):
        s = scan.parse(desktop_raw(), [], {}, False)
        self.assertEqual(s.gpu.vram_gb, 4.0)

    def test_laptop_on_battery_single_item_dicts(self):
        s = scan.parse(laptop_raw(), MON60, {}, True)
        self.assertTrue(s.is_laptop)
        self.assertTrue(s.on_battery)
        self.assertEqual(s.threads, 8)
        self.assertEqual(s.ram_sticks, 1)
        self.assertEqual(s.ram_mhz, 2666)  # ConfiguredClockSpeed пуст: берётся Speed
        self.assertEqual(len(s.disks), 1)
        self.assertEqual(s.disks[0].kind, "nvme")
        self.assertEqual(s.gpu.name, "NVIDIA GeForce GTX 1650")  # Intel UHD не считается дискретной

    def test_on_battery_ignored_on_desktop(self):
        self.assertFalse(scan.parse(desktop_raw(), [], {}, True).on_battery)

    def test_empty(self):
        for raw in ({}, None, {"cpu": None, "ram": None, "gpu": None, "os": None, "disks": None}):
            s = scan.parse(raw, [], {}, False)
            self.assertEqual((s.threads, s.ram_gb, s.gpus, s.disks, s.os_build), (0, 0, [], [], 0))
            self.assertIsNone(s.gpu)
            self.assertIsNone(s.monitor)
            self.assertEqual(s.tier, "low")
            self.assertTrue(0 <= s.score <= 39)
            self.assertEqual(len(s.summary()), 7)

    def test_summary_labels(self):
        s = scan.parse(desktop_raw(), MON144, {}, False)
        self.assertEqual([k for k, _ in s.summary()],
                         ["Процессор", "Память", "Видеокарта", "Монитор", "Диски", "Windows", "Тип ПК"])


class TierTests(unittest.TestCase):
    def tier(self, score):
        with mock.patch.object(Specs, "score", property(lambda self: score)):
            return make(nv()).tier

    def test_boundaries(self):
        self.assertEqual(self.tier(39), "low")
        self.assertEqual(self.tier(40), "mid")
        self.assertEqual(self.tier(69), "mid")
        self.assertEqual(self.tier(70), "high")

    def test_no_gpu_or_integrated_is_low(self):
        self.assertEqual(make(None).tier, "low")
        self.assertEqual(make(GpuInfo("Intel(R) UHD Graphics", "intel", "", 1.0)).tier, "low")
        self.assertEqual(make(GpuInfo("AMD Radeon(TM) Graphics", "amd", "", 0.5)).tier, "low")

    def test_realistic_tiers(self):
        self.assertEqual(make(nv("NVIDIA GeForce RTX 4070", 12.0)).tier, "high")
        self.assertEqual(make(nv("NVIDIA GeForce RTX 2060", 6.0), 12, 16, "ssd").tier, "mid")
        self.assertEqual(make(nv("NVIDIA GeForce GTX 1050", 2.0), 8, 8, "hdd").tier, "low")


class HagsTests(unittest.TestCase):
    def test_models(self):
        yes = [("NVIDIA GeForce RTX 3060", "nvidia"), ("NVIDIA GeForce GTX 1060 6GB", "nvidia"),
               ("NVIDIA GeForce GTX 1660 SUPER", "nvidia"), ("AMD Radeon RX 5700 XT", "amd"),
               ("AMD Radeon RX 7800 XT", "amd")]
        no = [("NVIDIA GeForce GTX 960", "nvidia"), ("NVIDIA GeForce GTX 750 Ti", "nvidia"),
              ("AMD Radeon RX 580", "amd"), ("AMD Radeon RX 480", "amd"), ("Intel(R) UHD Graphics", "intel"), ("", "other")]
        for n, v in yes:
            self.assertTrue(recommend.supports_hags(n, v), n)
        for n, v in no:
            self.assertFalse(recommend.supports_hags(n, v), n)


class RecommendTests(unittest.TestCase):
    def test_nvidia_high(self):
        p = recommend.build(make(nv("NVIDIA GeForce RTX 4070", 12.0)))
        self.assertEqual(p.game_tier, "high")
        self.assertEqual(p.gpu_values["lowlat"], 2)
        self.assertNotIn("texq", p.gpu_keys)
        self.assertNotIn("texq", p.gpu_values)
        self.assertEqual(p.gpu_values["fpslimit"], 141)
        self.assertIn("vsync", p.gpu_keys)
        self.assertTrue(p.notes)

    def test_nvidia_mid(self):
        p = recommend.build(make(nv("NVIDIA GeForce RTX 2060", 6.0), 12, 16, "ssd", MON60))
        self.assertEqual(p.game_tier, "mid")
        self.assertEqual(p.gpu_values["lowlat"], 2)
        self.assertEqual(p.gpu_values["texq"], 10)
        self.assertIn("texq", p.gpu_keys)

    def test_nvidia_low(self):
        p = recommend.build(make(nv("NVIDIA GeForce GTX 1050", 2.0), 8, 8, "hdd", MON60))
        self.assertEqual(p.game_tier, "low")
        self.assertNotIn("lowlat", p.gpu_values)  # 1 (Вкл) совпадает со значением по умолчанию
        self.assertNotIn("texq", p.gpu_values)
        self.assertIn("texq", p.gpu_keys)
        self.assertIn("lowlat", p.gpu_keys)
        titles = " ".join(t for t, _ in p.notes)
        self.assertIn("Мало оперативной памяти", titles)
        self.assertIn("HDD", titles)

    def test_fps_cap_from_hz(self):
        g = nv()
        for hz, cap in ((60, None), (119, None), (120, 117), (165, 162), (240, 237)):
            p = recommend.build(make(g, mons=[Monitor(1920, 1080, hz, True)]))
            self.assertEqual(p.gpu_values.get("fpslimit"), cap, hz)
            self.assertIn("fpslimit", p.gpu_keys)
        p = recommend.build(make(g, mons=[]))
        self.assertNotIn("fpslimit", p.gpu_values)

    def test_amd_laptop_skips_ulps(self):
        g = GpuInfo("AMD Radeon RX 6600M", "amd", "1", 8.0)
        p = recommend.build(make(g, laptop=True, battery=True))
        self.assertNotIn("ulps", p.gpu_keys)
        self.assertEqual(len(p.gpu_keys), len(gpu.AMD) - 1)
        self.assertNotIn("power", p.tweak_ids)  # ноутбук от батареи
        p = recommend.build(make(g))
        self.assertEqual(p.gpu_keys, [s.key for s in gpu.AMD])

    def test_intel_only(self):
        p = recommend.build(make(GpuInfo("Intel(R) UHD Graphics 630", "intel", "", 1.0), 8, 8, "ssd", MON60))
        self.assertEqual(p.gpu_keys, [])
        self.assertEqual(p.game_tier, "low")
        self.assertNotIn("hags", p.tweak_ids)
        self.assertTrue(any("Драйвер" in t for t, _ in p.notes))
        self.assertEqual(recommend.build(make(None)).gpu_keys, [])

    def test_tweaks(self):
        ids = {t.id for t in system_tweaks.TWEAKS}
        p = recommend.build(make(nv()))
        self.assertEqual(p.tweak_ids, ["power", "gamemode", "dvr", "hags", "mmcss", "mouse", "net"])
        self.assertTrue(set(p.tweak_ids) <= ids)
        self.assertNotIn("temp", p.tweak_ids)
        self.assertNotIn("hags", recommend.build(make(nv(), build=18363)).tweak_ids)
        self.assertNotIn("hags", recommend.build(make(nv("NVIDIA GeForce GTX 960", 4.0))).tweak_ids)
        self.assertIn("power", recommend.build(make(nv(), laptop=True, battery=False)).tweak_ids)
        self.assertNotIn("power", recommend.build(make(nv(), laptop=True, battery=True)).tweak_ids)

    def test_gpu_keys_exist(self):
        keys = {s.key for s in gpu.NVIDIA}
        p = recommend.build(make(nv()))
        self.assertTrue(set(p.gpu_keys) <= keys and set(p.gpu_values) <= keys)

    def test_advice_notes(self):
        p = recommend.build(make(nv(), sticks=1, mhz=2400, free=10.0))
        titles = " ".join(t for t, _ in p.notes)
        for part in ("Одна планка", "Память работает медленно", "Мало места", "Проверь частоту"):
            self.assertIn(part, titles)


class SmokeTest(unittest.TestCase):
    def test_real_scan(self):
        s = scan.scan()
        self.assertIsInstance(s, Specs)
        self.assertIn(s.tier, ("low", "mid", "high"))


if __name__ == "__main__":
    unittest.main()
