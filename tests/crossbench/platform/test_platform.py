# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime as dt
import pathlib
import sys
import unittest

import pytest

from crossbench.platform import Platform, DEFAULT_PLATFORM, MachineArch
from crossbench.platform.macos import MacOSPlatform
from crossbench.platform.posix import PosixPlatform
from crossbench.platform.win import WinPlatform


class MachineArchTestCase(unittest.TestCase):

  def test_is_arm(self):
    self.assertFalse(MachineArch.IA32.is_arm)
    self.assertFalse(MachineArch.X64.is_arm)
    self.assertTrue(MachineArch.ARM_32.is_arm)
    self.assertTrue(MachineArch.ARM_64.is_arm)

  def test_is_intel(self):
    self.assertTrue(MachineArch.IA32.is_intel)
    self.assertTrue(MachineArch.X64.is_intel)
    self.assertFalse(MachineArch.ARM_32.is_intel)
    self.assertFalse(MachineArch.ARM_64.is_intel)

  def test_is_32bit(self):
    self.assertTrue(MachineArch.IA32.is_32bit)
    self.assertFalse(MachineArch.X64.is_32bit)
    self.assertTrue(MachineArch.ARM_32.is_32bit)
    self.assertFalse(MachineArch.ARM_64.is_32bit)

  def test_is_64bit(self):
    self.assertFalse(MachineArch.IA32.is_64bit)
    self.assertTrue(MachineArch.X64.is_64bit)
    self.assertFalse(MachineArch.ARM_32.is_64bit)
    self.assertTrue(MachineArch.ARM_64.is_64bit)

  def test_str(self):
    self.assertEqual(str(MachineArch.IA32), "ia32")
    self.assertEqual(str(MachineArch.X64), "x64")
    self.assertEqual(str(MachineArch.ARM_32), "arm32")
    self.assertEqual(str(MachineArch.ARM_64), "arm64")


class PlatformTestCase(unittest.TestCase):

  def setUp(self):
    self.platform: Platform = DEFAULT_PLATFORM

  def test_sleep(self):
    self.platform.sleep(0)
    self.platform.sleep(0.01)
    self.platform.sleep(dt.timedelta())
    self.platform.sleep(dt.timedelta(seconds=0.1))

  def test_cpu_details(self):
    details = self.platform.cpu_details()
    self.assertLess(0, details["physical cores"])

  def test_get_relative_cpu_speed(self):
    self.assertGreater(self.platform.get_relative_cpu_speed(), 0)

  def test_is_thermal_throttled(self):
    self.assertIsInstance(self.platform.is_thermal_throttled(), bool)

  def test_is_battery_powered(self):
    self.assertIsInstance(self.platform.is_battery_powered, bool)

  def test_cpu_usage(self):
    self.assertGreaterEqual(self.platform.cpu_usage(), 0)

  def test_system_details(self):
    self.assertIsNotNone(self.platform.system_details())


@unittest.skipIf(not DEFAULT_PLATFORM.is_win, "Incompatible platform")
class WinPlatformUnittest(unittest.TestCase):
  platform: WinPlatform

  def setUp(self):
    super().setUp()
    assert isinstance(DEFAULT_PLATFORM, WinPlatform)
    self.platform = DEFAULT_PLATFORM

  def test_sh(self):
    ls = self.platform.sh_stdout("ls")
    self.assertTrue(ls)

  def test_search_binary(self):
    with self.assertRaises(ValueError):
      self.platform.search_binary(pathlib.Path("does not exist"))
    path = self.platform.search_binary(
        pathlib.Path("Windows NT/Accessories/wordpad.exe"))
    self.assertTrue(path and path.exists())

  def test_app_version(self):
    path = self.platform.search_binary(
        pathlib.Path("Windows NT/Accessories/wordpad.exe"))
    self.assertTrue(path and path.exists())
    version = self.platform.app_version(path)
    self.assertIsNotNone(version)

  def test_is_macos(self):
    self.assertFalse(self.platform.is_macos)
    self.assertFalse(self.platform.is_linux)
    self.assertTrue(self.platform.is_win)
    self.assertFalse(self.platform.is_remote)


@unittest.skipIf(not DEFAULT_PLATFORM.is_posix, "Incompatible platform")
class PosixPlatformUnittest(unittest.TestCase):
  platform: PosixPlatform

  def setUp(self):
    super().setUp()
    assert isinstance(DEFAULT_PLATFORM, PosixPlatform)
    self.platform: PosixPlatform = DEFAULT_PLATFORM

  def test_sh(self):
    ls = self.platform.sh_stdout("ls")
    self.assertTrue(ls)
    lsa = self.platform.sh_stdout("ls", "-a")
    self.assertTrue(lsa)
    self.assertNotEqual(ls, lsa)

  def test_which(self):
    ls_bin = self.platform.which("ls")
    bash_bin = self.platform.which("bash")
    self.assertNotEqual(ls_bin, bash_bin)
    self.assertTrue(pathlib.Path(ls_bin).exists())
    self.assertTrue(pathlib.Path(bash_bin).exists())

  def test_system_details(self):
    details = self.platform.system_details()
    self.assertTrue(details)


@unittest.skipIf(not DEFAULT_PLATFORM.is_macos, "Incompatible platform")
class MacOSPlatformHelperTestCase(unittest.TestCase):
  platform: MacOSPlatform

  def setUp(self):
    super().setUp()
    assert isinstance(DEFAULT_PLATFORM, MacOSPlatform)
    self.platform = DEFAULT_PLATFORM

  def test_search_binary_not_found(self):
    with self.assertRaises(ValueError):
      self.platform.search_binary(pathlib.Path("Invalid App Name"))
    binary = self.platform.search_binary(pathlib.Path("Non-existent App.app"))
    self.assertIsNone(binary)

  def test_search_binary(self):
    binary = self.platform.search_binary(pathlib.Path("Safari.app"))
    self.assertTrue(binary and binary.is_file())

  def test_search_app(self):
    binary = self.platform.search_app(pathlib.Path("Safari.app"))
    self.assertTrue(binary and binary.exists())
    self.assertTrue(binary and binary.is_dir())

  def test_name(self):
    self.assertEqual(self.platform.name, "macos")

  def test_is_macos(self):
    self.assertTrue(self.platform.is_macos)
    self.assertFalse(self.platform.is_linux)
    self.assertFalse(self.platform.is_win)
    self.assertFalse(self.platform.is_remote)

  def test_set_main_screen_brightness(self):
    prev_level = DEFAULT_PLATFORM.get_main_display_brightness()
    brightness_level = 32
    DEFAULT_PLATFORM.set_main_display_brightness(brightness_level)
    self.assertEqual(brightness_level,
                     DEFAULT_PLATFORM.get_main_display_brightness())
    DEFAULT_PLATFORM.set_main_display_brightness(prev_level)
    self.assertEqual(prev_level, DEFAULT_PLATFORM.get_main_display_brightness())


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
