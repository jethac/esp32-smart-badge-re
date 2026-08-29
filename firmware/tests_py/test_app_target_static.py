import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "firmware/overlay/SDK/apps/watch"


class AppTargetStaticTest(unittest.TestCase):
    def test_boot_adapter_requires_every_authoritative_source(self) -> None:
        source = (OVERLAY / "include/e87/e87_app_target.h").read_text(encoding="utf-8")
        for reader in (
            "read_now_ms",
            "read_has_bond",
            "read_reset_cause",
            "read_key",
            "read_charge",
        ):
            self.assertIn(f"port->{reader} == NULL", source)
            self.assertIn(f"port->{reader}(port->context", source)
        self.assertIn("*out_event = event;", source)
        self.assertLess(source.index("read_charge(port->context"), source.index("*out_event = event;"))

    def test_app_has_no_synthetic_time_or_charger_initialization(self) -> None:
        source = (OVERLAY / "e87/e87_app.c").read_text(encoding="utf-8")
        self.assertNotIn("e87_runtime_now_ms", source)
        self.assertNotIn("charge_start", source)
        self.assertNotIn("e87_br35_battery_charge_init", source)
        self.assertIn("e87_boot_port.read_now_ms", source)
        self.assertIn("e87_ble_target_init", source)
        self.assertIn("e87_ble_target_poll", source)
        self.assertIn("e87_ble_target_set_writes_enabled", source)

    def test_unsupported_effects_fail_closed(self) -> None:
        source = (OVERLAY / "e87/e87_app.c").read_text(encoding="utf-8")
        effect = source.split("static bool e87_emit_effect", 1)[1].split("static bool e87_try_enqueue_state", 1)[0]
        self.assertIn("E87_APP_CORE_EFFECT_BLE_SET_WRITES", effect)
        self.assertTrue(effect.rstrip().endswith("}"))
        self.assertIn("return false;", effect)


if __name__ == "__main__":
    unittest.main()
