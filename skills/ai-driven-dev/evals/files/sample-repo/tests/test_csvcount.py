import unittest

import csvcount


class CountRowsTest(unittest.TestCase):
    def test_counts_all_lines(self):
        self.assertEqual(csvcount.count_rows(["a,b", "1,2"]), 2)


if __name__ == "__main__":
    unittest.main()
