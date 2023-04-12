# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from utils import any_memory_to_bytes, generate_random_password, split_mem


class TestUtils(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(True)

    def test_generate_random_password(self):
        password = generate_random_password(16)
        self.assertEqual(len(password), 16)
        self.assertTrue(password.isalnum())

    def test_split_mem(self):
        self.assertEqual(split_mem("1Gi"), ("1", "Gi"))
        self.assertEqual(split_mem("1G"), ("1", "G"))
        self.assertEqual(split_mem("1"), (None, "No unit found"))

    def test_any_memory_to_bytes(self):
        self.assertEqual(any_memory_to_bytes("1Gi"), 1073741824)
        self.assertEqual(any_memory_to_bytes("1G"), 10**9)
        self.assertEqual(any_memory_to_bytes("1024"), 1024)
