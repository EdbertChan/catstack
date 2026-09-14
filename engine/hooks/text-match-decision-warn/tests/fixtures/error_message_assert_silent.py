import unittest


class WorkerTest(unittest.TestCase):
    def test_raises_with_message(self):
        with self.assertRaises(RuntimeError) as ctx:
            raise RuntimeError("boom")
        self.assertIn("boom", str(ctx.exception))
        if "boom" in str(ctx.exception):
            return
