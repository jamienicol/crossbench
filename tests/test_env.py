# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import pathlib
import hjson
import unittest
from unittest import mock

import sys
from pathlib import Path

# Fix the path so that crossbench modules are importable
root_dir = Path(__file__).parents[1]
sys.path.insert(0, str(root_dir))

import crossbench as cb
import crossbench.runner
import crossbench.env

import pytest


class HostEnvironmentConfigTestCase(unittest.TestCase):

  def test_combine_bool_value(self):
    default = cb.env.HostEnvironmentConfig()
    self.assertIsNone(default.power_use_battery)

    battery = cb.env.HostEnvironmentConfig(power_use_battery=True)
    self.assertTrue(battery.power_use_battery)
    self.assertTrue(battery.merge(battery).power_use_battery)
    self.assertTrue(default.merge(battery).power_use_battery)
    self.assertTrue(battery.merge(default).power_use_battery)

    power = cb.env.HostEnvironmentConfig(power_use_battery=False)
    self.assertFalse(power.power_use_battery)
    self.assertFalse(power.merge(power).power_use_battery)
    self.assertFalse(default.merge(power).power_use_battery)
    self.assertFalse(power.merge(default).power_use_battery)

    with self.assertRaises(ValueError):
      combined = power.merge(battery)

  def test_combine_min_float_value(self):
    default = cb.env.HostEnvironmentConfig()
    self.assertIsNone(default.cpu_min_relative_speed)

    high = cb.env.HostEnvironmentConfig(cpu_min_relative_speed=1)
    self.assertEqual(high.cpu_min_relative_speed, 1)
    self.assertEqual(high.merge(high).cpu_min_relative_speed, 1)
    self.assertEqual(default.merge(high).cpu_min_relative_speed, 1)
    self.assertEqual(high.merge(default).cpu_min_relative_speed, 1)

    low = cb.env.HostEnvironmentConfig(cpu_min_relative_speed=0.5)
    self.assertEqual(low.cpu_min_relative_speed, 0.5)
    self.assertEqual(low.merge(low).cpu_min_relative_speed, 0.5)
    self.assertEqual(default.merge(low).cpu_min_relative_speed, 0.5)
    self.assertEqual(low.merge(default).cpu_min_relative_speed, 0.5)

    self.assertEqual(high.merge(low).cpu_min_relative_speed, 1)

  def test_combine_max_float_value(self):
    default = cb.env.HostEnvironmentConfig()
    self.assertIsNone(default.cpu_max_usage_percent)

    high = cb.env.HostEnvironmentConfig(cpu_max_usage_percent=100)
    self.assertEqual(high.cpu_max_usage_percent, 100)
    self.assertEqual(high.merge(high).cpu_max_usage_percent, 100)
    self.assertEqual(default.merge(high).cpu_max_usage_percent, 100)
    self.assertEqual(high.merge(default).cpu_max_usage_percent, 100)

    low = cb.env.HostEnvironmentConfig(cpu_max_usage_percent=0)
    self.assertEqual(low.cpu_max_usage_percent, 0)
    self.assertEqual(low.merge(low).cpu_max_usage_percent, 0)
    self.assertEqual(default.merge(low).cpu_max_usage_percent, 0)
    self.assertEqual(low.merge(default).cpu_max_usage_percent, 0)

    self.assertEqual(high.merge(low).cpu_max_usage_percent, 0)

  def test_parse_example_config_file(self):
    example_config_file = pathlib.Path(
        __file__).parent.parent / "config" / "env.config.example.hjson"
    if not example_config_file.exists():
      raise unittest.SkipTest(f"Test file {example_config_file} does not exist")
    with example_config_file.open() as f:
      data = hjson.load(f)
    config = cb.env.HostEnvironmentConfig(**data["env"])


class HostEnvironmentTestCase(unittest.TestCase):

  def setUp(self):
    self.mock_platform = mock.Mock()
    self.mock_platform.processes.return_value = []
    self.mock_runner = mock.Mock(
        platform=self.mock_platform, probes=[], browsers=[])

  def test_instantiate(self):
    env = cb.env.HostEnvironment(self.mock_runner)
    self.assertEqual(env.runner, self.mock_runner)

    config = cb.env.HostEnvironmentConfig()
    env = cb.env.HostEnvironment(self.mock_runner, config)
    self.assertEqual(env.runner, self.mock_runner)
    self.assertEqual(env.config, config)

  def test_warn_mode_skip(self):
    config = cb.env.HostEnvironmentConfig()
    env = cb.env.HostEnvironment(self.mock_runner, config,
                                 cb.env.ValidationMode.SKIP)
    env.handle_warning("foo")

  def test_warn_mode_fail(self):
    config = cb.env.HostEnvironmentConfig()
    env = cb.env.HostEnvironment(self.mock_runner, config,
                                 cb.env.ValidationMode.THROW)
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.handle_warning("custom env check warning")
    self.assertIn("custom env check warning", str(cm.exception))

  def test_warn_mode_prompt(self):
    config = cb.env.HostEnvironmentConfig()
    env = cb.env.HostEnvironment(self.mock_runner, config,
                                 cb.env.ValidationMode.PROMPT)
    with mock.patch("builtins.input", return_value="Y") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])
    with mock.patch("builtins.input", return_value="n") as cm:
      with self.assertRaises(cb.env.ValidationError):
        env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_warn_mode_warn(self):
    config = cb.env.HostEnvironmentConfig()
    env = cb.env.HostEnvironment(self.mock_runner, config,
                                 cb.env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_validate_skip(self):
    env = cb.env.HostEnvironment(self.mock_runner,
                                 cb.env.HostEnvironmentConfig(),
                                 cb.env.ValidationMode.SKIP)
    env.validate()

  def test_validate_warn(self):
    env = cb.env.HostEnvironment(self.mock_runner,
                                 cb.env.HostEnvironmentConfig(),
                                 cb.env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_not_called()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_validate_warn_no_probes(self):
    env = cb.env.HostEnvironment(
        self.mock_runner, cb.env.HostEnvironmentConfig(require_probes=True),
        cb.env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_called_once()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_request_battery_power_on(self):
    env = cb.env.HostEnvironment(
        self.mock_runner, cb.env.HostEnvironmentConfig(power_use_battery=True),
        cb.env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    env.validate()

    self.mock_platform.is_battery_powered = False
    with self.assertRaises(Exception) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

  def test_request_battery_power_off(self):
    env = cb.env.HostEnvironment(
        self.mock_runner, cb.env.HostEnvironmentConfig(power_use_battery=False),
        cb.env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

    self.mock_platform.is_battery_powered = False
    env.validate()

  def test_request_battery_power_off_conflicting_probe(self):
    env = cb.env.HostEnvironment(
        self.mock_runner, cb.env.HostEnvironmentConfig(power_use_battery=False),
        cb.env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = False

    mock_probe = mock.Mock()
    mock_probe.configure_mock(BATTERY_ONLY=True, name="mock_probe")
    self.mock_runner.probes = [mock_probe]

    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()
    message = str(cm.exception).lower()
    self.assertIn("mock_probe", message)
    self.assertIn("battery", message)

    mock_probe.BATTERY_ONLY = False
    env.validate()

  def test_request_is_headless_default(self):
    env = cb.env.HostEnvironment(
        self.mock_runner,
        cb.env.HostEnvironmentConfig(
            browser_is_headless=cb.env.HostEnvironmentConfig.Ignore),
        cb.env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    env.validate()

    mock_browser.is_headless = True
    env.validate()

  def test_request_is_headless_true(self):
    env = cb.env.HostEnvironment(
        self.mock_runner,
        cb.env.HostEnvironmentConfig(browser_is_headless=True),
        cb.env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    self.mock_platform.has_display = True
    mock_browser.is_headless = False
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))

    self.mock_platform.has_display = False
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()

    self.mock_platform.has_display = True
    mock_browser.is_headless = True
    env.validate()

    self.mock_platform.has_display = False
    env.validate()

  def test_request_is_headless_false(self):
    env = cb.env.HostEnvironment(
        self.mock_runner,
        cb.env.HostEnvironmentConfig(browser_is_headless=False),
        cb.env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    self.mock_platform.has_display = True
    mock_browser.is_headless = False
    env.validate()

    self.mock_platform.has_display = False
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()

    self.mock_platform.has_display = True
    mock_browser.is_headless = True
    with self.assertRaises(cb.env.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
