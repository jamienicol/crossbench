# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from crossbench.flags import ChromeFeatures, ChromeFlags, Flags, JSFlags


class TestFlags(unittest.TestCase):

  CLASS = Flags

  def test_construct(self):
    flags = self.CLASS()
    self.assertEqual(len(flags), 0)
    self.assertNotIn("foo", flags)

  def test_construct_dict(self):
    flags = self.CLASS({"--foo": "v1", "--bar": "v2"})
    self.assertIn("--foo", flags)
    self.assertIn("--bar", flags)
    self.assertEqual(flags["--foo"], "v1")
    self.assertEqual(flags["--bar"], "v2")

  def test_construct_list(self):
    flags = self.CLASS(("--foo", "--bar"))
    self.assertIn("--foo", flags)
    self.assertIn("--bar", flags)
    self.assertIsNone(flags["--foo"])
    self.assertIsNone(flags["--bar"])
    with self.assertRaises(AssertionError):
      self.CLASS(("--foo=v1", "--bar=v2"))
    flags = self.CLASS((("--foo", "v3"), "--bar"))
    self.assertEqual(flags["--foo"], "v3")
    self.assertIsNone(flags["--bar"])

  def test_construct_flags(self):
    original_flags = self.CLASS({"--foo": "v1", "--bar": "v2"})
    flags = self.CLASS(original_flags)
    self.assertIn("--foo", flags)
    self.assertIn("--bar", flags)
    self.assertEqual(flags["--foo"], "v1")
    self.assertEqual(flags["--bar"], "v2")

  def test_set(self):
    flags = self.CLASS()
    flags["--foo"] = "v1"
    with self.assertRaises(AssertionError):
      flags["--foo"] = "v2"
    # setting the same value is ok
    flags["--foo"] = "v1"
    self.assertEqual(flags["--foo"], "v1")
    flags.set("--bar")
    self.assertIn("--foo", flags)
    self.assertIn("--bar", flags)
    self.assertIsNone(flags["--bar"])
    with self.assertRaises(AssertionError):
      flags.set("--bar", "v3")
    flags.set("--bar", "v4", override=True)
    self.assertEqual(flags["--foo"], "v1")
    self.assertEqual(flags["--bar"], "v4")

  def test_get_list(self):
    flags = self.CLASS({"--foo": "v1", "--bar": None})
    self.assertEqual(list(flags.get_list()), ["--foo=v1", "--bar"])

  def test_copy(self):
    flags = self.CLASS({"--foo": "v1", "--bar": None})
    copy = flags.copy()
    self.assertEqual(list(flags.get_list()), list(copy.get_list()))

  def test_update(self):
    flags = self.CLASS({"--foo": "v1", "--bar": None})
    with self.assertRaises(AssertionError):
      flags.update({"--bar": "v2"})
    self.assertEqual(flags["--foo"], "v1")
    self.assertIsNone(flags["--bar"])
    flags.update({"--bar": "v2"}, override=True)
    self.assertEqual(flags["--foo"], "v1")
    self.assertEqual(flags["--bar"], "v2")

  def test_str_basic(self):
    flags = self.CLASS({"--foo": None})
    self.assertEqual(str(flags), "--foo")
    flags = self.CLASS({"--foo": "bar"})
    self.assertEqual(str(flags), "--foo=bar")

  def test_str_multiple(self):
    flags = self.CLASS({
        "--flag1": "value1",
        "--flag2": None,
        "--flag3": "value3"
    })
    self.assertEqual(str(flags), "--flag1=value1 --flag2 --flag3=value3")


class TestChromeFlags(TestFlags):

  CLASS = ChromeFlags

  def test_js_flags(self):
    flags = self.CLASS({
        "--foo": None,
        "--bar": "v1",
    })
    self.assertIsNone(flags["--foo"])
    self.assertEqual(flags["--bar"], "v1")
    self.assertNotIn("--js-flags", flags)
    with self.assertRaises(AssertionError):
      flags["--js-flags"] = "--js-foo, --no-js-foo"
    flags["--js-flags"] = "--js-foo=v3, --no-js-bar"
    with self.assertRaises(AssertionError):
      flags["--js-flags"] = "--js-foo=v4, --no-js-bar"
    js_flags = flags.js_flags
    self.assertEqual(js_flags["--js-foo"], "v3")
    self.assertIsNone(js_flags["--no-js-bar"])

  def test_js_flags_initial_data(self):
    flags = self.CLASS({
        "--js-flags": "--foo=v1,--no-bar",
    })
    js_flags = flags.js_flags
    self.assertEqual(js_flags["--foo"], "v1")
    self.assertIsNone(js_flags["--no-bar"])

  def test_features(self):
    flags = self.CLASS()
    features = flags.features
    self.assertTrue(features.is_empty)
    flags["--enable-features"] = "F1,F2"
    with self.assertRaises(AssertionError):
      flags["--disable-features"] = "F1,F2"
    with self.assertRaises(AssertionError):
      flags["--disable-features"] = "F2,F1"
    flags["--disable-features"] = "F3,F4"
    self.assertEqual(features.enabled, {"F1": None, "F2": None})
    self.assertEqual(features.disabled, set(("F3", "F4")))


class TestJSFlags(TestFlags):

  CLASS = JSFlags

  def test_conflicting_flags(self):
    with self.assertRaises(AssertionError):
      flags = self.CLASS(("--foo", "--no-foo"))
    with self.assertRaises(AssertionError):
      flags = self.CLASS(("--foo", "--nofoo"))
    flags = self.CLASS(("--foo", "--no-bar"))
    self.assertIsNone(flags["--foo"])
    self.assertIsNone(flags["--no-bar"])
    self.assertIn("--foo", flags)
    self.assertNotIn("--no-foo", flags)
    self.assertNotIn("--bar", flags)
    self.assertIn("--no-bar", flags)

  def test_conflicting_override(self):
    flags = self.CLASS(("--foo", "--no-bar"))
    with self.assertRaises(AssertionError):
      flags.set("--no-foo")
    with self.assertRaises(AssertionError):
      flags.set("--nofoo")
    flags.set("--nobar")
    with self.assertRaises(AssertionError):
      flags.set("--bar")
    with self.assertRaises(AssertionError):
      flags.set("--foo", "v2")
    self.assertIsNone(flags["--foo"])
    self.assertIsNone(flags["--no-bar"])
    flags.set("--no-foo", override=True)
    self.assertNotIn("--foo", flags)
    self.assertIn("--no-foo", flags)
    self.assertNotIn("--bar", flags)
    self.assertIn("--no-bar", flags)

  def test_str_multiple(self):
    flags = self.CLASS({
        "--flag1": "value1",
        "--flag2": None,
        "--flag3": "value3"
    })
    self.assertEqual(str(flags), "--flag1=value1,--flag2,--flag3=value3")
