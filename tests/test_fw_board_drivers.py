"""Host tests for the board drivers and the board configuration (no hardware, no SWD).

Drivers are exercised against simulated hardware in firmware/stm32f407/tests/fv_drivers_test.c (bit-level I2C/SCCB
slave with OV2640/TCS34725/SSD1306 models, GPIO/ADC register mocks, DHT22 waveform simulator)."""

import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/stm32f407"
ZIG = [sys.executable, "-m", "ziglang"]
DRIVERS = ["fv_bitbang_bus.c", "fv_ov2640.c", "fv_tcs34725.c", "fv_ssd1306.c", "fv_dht22.c", "fv_gpio.c", "fv_adc.c",
           "fv_entc_ph.c"]
INC = [f"-I{p}" for p in (FW / "app", FW / "board", FW / "drivers", FW / "platform", FW / "vision", FW / "generated",
                           ROOT / "firmware/model2", ROOT / "models/model2_export", ROOT / "firmware/image",
                           ROOT / "firmware/memory")]


def _need_zig():
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")


def test_driver_simulations(tmp_path):
    _need_zig()
    exe = tmp_path / "drv.exe"
    r = subprocess.run(ZIG + ["cc", "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", f"-I{FW / 'drivers'}",
                              f"-I{FW / 'generated'}", "-o", str(exe), str(FW / "tests/fv_drivers_test.c"),
                              *[str(FW / "drivers" / d) for d in DRIVERS]], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    lines = p.stdout.splitlines()
    assert p.returncode == 0 and lines[-1] == "END fails=0", p.stdout
    passed = [l for l in lines if l.startswith("PASS")]
    assert len(passed) == 61
    for name in ("ov2640_all_table_values_written", "tcs_entc_settings_atime_gain_enable", "oled_entc_init_sequence",
                 "oled_flush_entc_per_page_b0_00_10_plus_128", "oled_bottom_rows_5_6_7_transferred",
                 "dht_full_transaction_simulated", "i2c_repeated_start_burst_read", "adc_single_conversion_ch3_480cycles",
                 "dht_start_pulse_20ms_entc", "dht_irq_off_after_start_pulse_and_restored", "entc_ph_smoothing",
                 "dht11_decode_valid_55rh_24c", "dht11_invalid_checksum", "dht11_out_of_range",
                 "dht11_full_transaction_20ms_irq_restored", "dht11_no_response", "dht11_timeout_mid_frame"):
        assert f"PASS {name}" in lines


def test_platform_and_drivers_compile_for_cortex_m4f(tmp_path):
    _need_zig()
    srcs = [FW / "platform/fv_platform_stm32.c", FW / "app/fv_diag.c", FW / "app/main.c"] + [FW / "drivers" / d for d in DRIVERS]
    for s in srcs:
        r = subprocess.run(ZIG + ["cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard", "-std=c99",
                                  "-Os", "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion", *INC, "-c", str(s),
                                  "-o", str(tmp_path / (s.name + ".o"))], capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stderr)


def test_entc_ov2640_tables_match_backup(tmp_path):
    out = tmp_path / "t.h"
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/extract_entc_config.py"), str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.read_text() == (FW / "generated/fv_entc_ov2640_tables.h").read_text(), "generated table header is stale"
    b = (ROOT / "backups/board_original_firmware/board_flash_0x08000000_512K.bin").read_bytes()
    h = (FW / "generated/fv_entc_ov2640_tables.h").read_text()
    a = re.search(r"TABLE_A\[157\] = \{(.*?)\};", h, re.S).group(1)
    pairs = [(int(x, 16), int(y, 16)) for x, y in re.findall(r"\{0x([0-9A-F]{2}), 0x([0-9A-F]{2})\}", a)]
    raw = b[0x711C:0x711C + 314]
    assert pairs == [(raw[i], raw[i + 1]) for i in range(0, 314, 2)]


def test_board_config_has_no_guessed_values():
    h = (FW / "board/fv_board_config.h").read_text()
    # pH/MQ135 mapping recovered from the ENTC firmware code (docs/BOARD_PIN_MAP_EVIDENCE.md), labelled STATIC
    assert re.search(r"#define FV_ADC_CH_PH 2 .*\[STATIC: ENTC code\]", h)
    assert re.search(r"#define FV_ADC_CH_MQ135 3 .*\[STATIC: ENTC code\]", h)
    assert re.search(r"#define FV_INDICATOR_KIND FV_BOARD_UNKNOWN", h)                # still unknown
    for tag in ("[STATIC", "[LIVE]", "[UNKNOWN]"):
        assert tag in h
    assert "#define FV_DCMI_VSPOL 0" in h and "#define FV_DCMI_HSPOL 0" in h       # read live over SWD
    p = (FW / "platform/fv_platform_stm32.c").read_text()
    # pesticide risk can never become PREDICTED from device data: no device->Model 2 calibration profile
    assert "has_calibration_profile = 0" in p and "has_calibration_profile = 1" not in p
    assert "fv_entc_ph_update" in p and "ENTC calibration" in p
    ph = (FW / "drivers/fv_entc_ph.h").read_text()
    assert "2.282f" in ph and "-5.263159275f" in ph and "0.05f" in ph            # constants decoded from the ENTC binary
    d = (FW / "drivers/fv_dht22.h").read_text()
    assert "#define FV_DHT22_START_LOW_US 20000u" in d
    assert "FV_DHT_FORMAT_DHT11}" in p                                         # sensor confirmed DHT11 (ENTC decoding)


def test_platform_uses_only_documented_pins():
    """Every pin the platform touches comes from fv_board_config.h macros (no literal pin numbers elsewhere)."""
    p = (FW / "platform/fv_platform_stm32.c").read_text()
    literal_pins = re.findall(r"\(fv_pin_t\)\{FV_PORT_[A-E], (\d+)\}", p)
    assert sorted(literal_pins) == ["2", "3"]                                    # PA2/PA3 analog (= FV_ADC_CH_A/B)
    h = (FW / "board/fv_board_config.h").read_text()
    assert "#define FV_ADC_CH_A 2" in h and "#define FV_ADC_CH_B 3" in h


@pytest.mark.parametrize("name", ["fv_app", "fv_app_v2"])
def test_app_firmware_build_report(name):
    rep = ROOT / f"reports/firmware/gcc/{name}_build_report.json"
    if not rep.exists():
        pytest.skip("app firmware not built (tools/firmware/build_gcc.sh)")
    d = json.loads(rep.read_text())
    assert d["all_checks_pass"], d["checks"]
    t = d["totals"]
    assert t["flash_used"] <= 512 * 1024 and t["ram_used_incl_stack_reserve"] <= 128 * 1024 and t["ccm_used"] <= 64 * 1024
    assert d["key_symbols"]["g_fv_model_data"]["size"] == 366848


def test_previous_firmware_artifacts_untouched():
    h = lambda p: hashlib.sha256((ROOT / "reports/firmware/gcc" / p).read_bytes()).hexdigest()
    assert h("fv_selftest.elf").startswith("71253b93")          # flashed + verified self-test
    assert h("fv_selftest_frame.bin").startswith("c8da9e1c")
    assert h("fv_fw.bin").startswith("ebcf635a")
    assert h("fv_app.elf").startswith("b9a394b2") and h("fv_app.bin").startswith("12e25e79")   # image flashed on 2026-10-17


def test_diag_reader_layout(tmp_path):
    pytest.importorskip("elftools")
    sys.path.insert(0, str(ROOT / "tools/firmware"))
    import read_diag as rd
    import read_selftest as rs
    elf = ROOT / "reports/firmware/gcc/fv_app.elf"
    if not elf.exists():
        pytest.skip("app firmware not built")
    addr, size = rs.symbol(elf, "g_fv_diag")
    assert size == rd.SIZE == 420 and 0x20000000 <= addr < 0x20020000
    b = bytearray(420)
    struct.pack_into("<II", b, 0, rd.MAGIC, 1)
    struct.pack_into("<i", b, 4 * rd.FIELDS_I32.index("fruit"), 0)
    struct.pack_into("<i", b, 4 * rd.FIELDS_I32.index("cam_pid"), 0x26)
    b[4 * len(rd.FIELDS_I32):4 * len(rd.FIELDS_I32) + 9] = b"FV1,ok\r\n\0"
    words = struct.unpack("<105I", bytes(b))
    text = "\n".join(f"0x{addr + 16 * i:08X} : " + " ".join(f"{w:08X}" for w in words[4 * i:4 * i + 4]) for i in range(27))
    d = rd.decode(rs.parse_r32(text, addr, 420))
    assert d["valid"] and d["cam_pid"] == 0x26 and d["serial_line"] == "FV1,ok"
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/read_diag.py")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "DRY RUN" in r.stdout and "mode=HOTPLUG" in r.stdout and "-r32" in r.stdout


def test_diag_reader_v2_layout():
    pytest.importorskip("elftools")
    sys.path.insert(0, str(ROOT / "tools/firmware"))
    import read_diag as rd
    import read_selftest as rs
    elf = ROOT / "reports/firmware/gcc/fv_app_v2.elf"
    if not elf.exists():
        pytest.skip("fv_app_v2 not built")
    addr, size = rs.symbol(elf, "g_fv_diag")
    assert size == rd.SIZE_V2 == 436
    f = rd.FIELDS_I32 + rd.FIELDS_V2
    b = bytearray(436)
    struct.pack_into("<II", b, 0, rd.MAGIC, 2)
    struct.pack_into("<i", b, 4 * f.index("ph_x100"), 891)
    struct.pack_into("<i", b, 4 * f.index("mq135_raw"), 396)
    d = rd.decode(bytes(b))
    assert d["valid"] and d["ph_entc_calibration"] == 8.91 and d["mq135_raw"] == 396
    struct.pack_into("<i", b, 4 * f.index("ph_x100"), -1)
    assert rd.decode(bytes(b))["ph_entc_calibration"] is None
