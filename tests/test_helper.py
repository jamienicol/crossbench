# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

import crossbench as cb


class TestMacOSPlatformHelper(unittest.TestCase):

  def test_set_main_screen_brightness(self):
    if cb.helper.platform.is_macos:
      brightness_level = 32
      cb.helper.platform.set_main_display_brightness(brightness_level)
      self.assertEqual(brightness_level,
                       cb.helper.platform.get_main_display_brightness())