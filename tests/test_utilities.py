import unittest

from CommonUtil import hbytes


class HumanReadableBytesCharacterizationTests(unittest.TestCase):
    def test_formats_bytes_and_unit_boundaries(self):
        cases = {
            0: "0.00bytes",
            1023: "1023.00bytes",
            1024: "1.00KB",
            1024**2: "1.00MB",
            1024**3: "1.00GB",
            1024**4: "1.00TB",
        }

        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(hbytes(value), expected)

    def test_formats_fractional_units_to_two_decimal_places(self):
        self.assertEqual(hbytes(1536), "1.50KB")


if __name__ == "__main__":
    unittest.main()
