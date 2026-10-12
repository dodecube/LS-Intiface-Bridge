import unittest

try:
    from .bridge import (
        full_payload,
        lovense_level_to_index,
        manufacturer_body,
        parse_command_message,
        parse_control_level,
        VIBRATION_COMMANDS,
    )
except ImportError:
    from bridge import (
        full_payload,
        lovense_level_to_index,
        manufacturer_body,
        parse_command_message,
        parse_control_level,
        VIBRATION_COMMANDS,
    )


class ProtocolTests(unittest.TestCase):
    def test_level_mapping(self):
        self.assertEqual(lovense_level_to_index(0), 0)
        self.assertEqual(lovense_level_to_index(1), 1)
        self.assertEqual(lovense_level_to_index(10), 5)
        self.assertEqual(lovense_level_to_index(20), 9)
        self.assertEqual(lovense_level_to_index(99), 9)
        self.assertEqual(lovense_level_to_index(-5), 0)

    def test_lovense_command_payload_matches_android_example(self):
        encoded = VIBRATION_COMMANDS[9]
        self.assertEqual(
            manufacturer_body(encoded),
            bytes.fromhex("6D B6 43 CE 97 FE 42 7C DC 57 D1"),
        )
        self.assertEqual(
            full_payload(encoded),
            bytes.fromhex("F0 FF 6D B6 43 CE 97 FE 42 7C DC 57 D1"),
        )

    def test_protocol_replies(self):
        self.assertEqual(parse_command_message("DeviceType;"), ["C:8A3D9FAC2A45:10;"])
        self.assertEqual(parse_command_message("Battery;"), ["99;"])
        self.assertEqual(parse_command_message("Status:1;"), ["2;"])
        self.assertEqual(parse_command_message("Vibrate:20;"), ["OK;"])
        self.assertEqual(parse_command_message("Vibrate:1;Rotate:2;"), ["OK;"])

    def test_parse_control_level(self):
        self.assertEqual(parse_control_level("Vibrate:17;", "Vibrate"), 17)
        self.assertEqual(parse_control_level("Rotate:42;", "Rotate"), 20)
        self.assertEqual(parse_control_level("Rotate:abc;", "Rotate"), 0)


if __name__ == "__main__":
    unittest.main()
