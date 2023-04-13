# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from argparse import ArgumentTypeError
import sys
import unittest
import pytest

from crossbench.browsers.splash_screen import SplashScreen, URLSplashScreen


class SplashScreenTestCase(unittest.TestCase):

  def test_prase_invalid(self):
    for invalid in ("a", "1", "{}"):
      with self.assertRaises(ArgumentTypeError):
        SplashScreen.parse(invalid)

  def test_parse_default(self):
    self.assertEqual(SplashScreen.parse(""), SplashScreen.DEFAULT)
    self.assertEqual(SplashScreen.parse("default"), SplashScreen.DEFAULT)

  def test_parse_named(self):
    self.assertEqual(SplashScreen.parse("none"), SplashScreen.NONE)
    self.assertEqual(SplashScreen.parse("minimal"), SplashScreen.MINIMAL)
    self.assertEqual(SplashScreen.parse("detailed"), SplashScreen.DETAILED)

  def test_parse_url(self):
    splash = SplashScreen.parse("http://splash.com")
    self.assertIsInstance(splash, URLSplashScreen)
    self.assertEqual(splash.url, "http://splash.com")

  def test_parse_file(self):
    splash = SplashScreen.parse(__file__)
    self.assertIsInstance(splash, URLSplashScreen)
    self.assertIn("file://", splash.url)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
