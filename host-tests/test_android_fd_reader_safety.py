import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READER = (
    ROOT
    / "src"
    / "main"
    / "java"
    / "com"
    / "openai"
    / "e87probe"
    / "AndroidFdPackageReader.java"
)


class AndroidFdPackageReaderSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = READER.read_text(encoding="utf-8")

    def test_open_is_no_follow_and_descriptor_owned(self):
        self.assertIn("Os.open(", self.source)
        self.assertIn("OsConstants.O_RDONLY", self.source)
        self.assertIn("OsConstants.O_NOFOLLOW", self.source)
        self.assertIn("OsConstants.O_CLOEXEC", self.source)
        self.assertIn("implements Closeable", self.source)
        self.assertIn("Os.close(current)", self.source)
        self.assertNotIn("getCanonical", self.source)

    def test_same_descriptor_is_verified_before_allocation_and_after_read(self):
        first_fstat = self.source.index("StructStat before = Os.fstat(fd)")
        regular_check = self.source.index("OsConstants.S_ISREG(before.st_mode)")
        size_check = self.source.index("size != expectedSize")
        allocation = self.source.index("new byte[expectedSize]")
        exact_read = self.source.index("Os.read(fd, bytes, offset")
        extra_read = self.source.index("Os.read(fd, extra, 0, 1)")
        second_fstat = self.source.index("StructStat after = Os.fstat(fd)")
        changed_check = self.source.index("after.st_size != size")

        self.assertLess(first_fstat, regular_check)
        self.assertLess(regular_check, size_check)
        self.assertLess(size_check, allocation)
        self.assertLess(allocation, exact_read)
        self.assertLess(exact_read, extra_read)
        self.assertLess(extra_read, second_fstat)
        self.assertLess(second_fstat, changed_check)
        self.assertIn("size > maxSize", self.source)
        self.assertIn("if (count <= 0)", self.source)
        self.assertIn("if (extraCount != 0)", self.source)


if __name__ == "__main__":
    unittest.main()
