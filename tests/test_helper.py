# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import pathlib
import unittest
import datetime as dt
import pyfakefs.fake_filesystem_unittest

import crossbench as cb
from crossbench.helper import Durations


class WaitTestCase(unittest.TestCase):

  def test_invalid_wait_ranges(self):
    with self.assertRaises(AssertionError):
      cb.helper.wait_range(min=-1)
    with self.assertRaises(AssertionError):
      cb.helper.wait_range(timeout=0)
    with self.assertRaises(AssertionError):
      cb.helper.wait_range(factor=0.2)

  def test_range(self):
    durations = list(
        cb.helper.wait_range(min=1, max=16, factor=2, max_iterations=5))
    self.assertListEqual(durations, [
        dt.timedelta(seconds=1),
        dt.timedelta(seconds=2),
        dt.timedelta(seconds=4),
        dt.timedelta(seconds=8),
        dt.timedelta(seconds=16)
    ])

  def test_range_extended(self):
    durations = list(
        cb.helper.wait_range(min=1, max=16, factor=2, max_iterations=5 + 4))
    self.assertListEqual(
        durations,
        [
            dt.timedelta(seconds=1),
            dt.timedelta(seconds=2),
            dt.timedelta(seconds=4),
            dt.timedelta(seconds=8),
            dt.timedelta(seconds=16),
            # After 5 iterations the interval is no longer increased
            dt.timedelta(seconds=16),
            dt.timedelta(seconds=16),
            dt.timedelta(seconds=16),
            dt.timedelta(seconds=16)
        ])


class DurationsTestCase(unittest.TestCase):

  def test_single(self):
    durations = Durations()
    self.assertTrue(len(durations) == 0)
    self.assertDictEqual(durations.to_json(), {})
    with durations.measure("a"):
      pass
    self.assertGreaterEqual(durations["a"].total_seconds(), 0)
    self.assertTrue(len(durations) == 1)

  def test_invalid_twice(self):
    durations = Durations()
    with durations.measure("a"):
      pass
    with self.assertRaises(AssertionError):
      with durations.measure("a"):
        pass
    self.assertTrue(len(durations) == 1)
    self.assertListEqual(list(durations.to_json().keys()), ["a"])

  def test_multiple(self):
    durations = Durations()
    for name in ["a", "b", "c"]:
      with durations.measure(name):
        pass
    self.assertEqual(len(durations), 3)
    self.assertListEqual(list(durations.to_json().keys()), ["a", "b", "c"])


class ChangeCWDTestCase(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    self.setUpPyfakefs()

  def test_basic(self):
    old_cwd = pathlib.Path.cwd()
    new_cwd = pathlib.Path("/foo/bar")
    new_cwd.mkdir(parents=True)
    with cb.helper.ChangeCWD(new_cwd):
      self.assertNotEqual(old_cwd, pathlib.Path.cwd())
      self.assertEqual(new_cwd, pathlib.Path.cwd())
    self.assertEqual(old_cwd, pathlib.Path.cwd())
    self.assertNotEqual(new_cwd, pathlib.Path.cwd())


class FileSizeTestCase(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    self.setUpPyfakefs()

  def test_empty(self):
    test_file = pathlib.Path('test.txt')
    test_file.touch()
    size = cb.helper.get_file_size(test_file)
    self.assertEqual(size, "0.00 B")


class TestMacOSPlatformHelper(unittest.TestCase):

  def test_set_main_screen_brightness(self):
    if not cb.helper.platform.is_macos:
      return
    prev_level = cb.helper.platform.get_main_display_brightness()
    brightness_level = 32
    cb.helper.platform.set_main_display_brightness(brightness_level)
    self.assertEqual(brightness_level,
                     cb.helper.platform.get_main_display_brightness())
    cb.helper.platform.set_main_display_brightness(prev_level)
    self.assertEqual(prev_level,
                     cb.helper.platform.get_main_display_brightness())
