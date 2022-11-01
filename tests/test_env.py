# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import crossbench as cb
from crossbench import runner
from crossbench import env as cb_env


class HostEnvironmentTestCase(unittest.TestCase):

  def setUp(self):
    self.mock_platform = mock.Mock()
    self.mock_runner = mock.Mock(platform=self.mock_platform, probes=[])

  def test_instantiate(self):
    env = cb_env.HostEnvironment(self.mock_runner)
    self.assertEqual(env.runner, self.mock_runner)

    config = cb_env.HostEnvironmentConfig()
    env = cb_env.HostEnvironment(self.mock_runner, config)
    self.assertEqual(env.runner, self.mock_runner)
    self.assertEqual(env.config, config)

  def test_warn_mode_skip(self):
    config = cb_env.HostEnvironmentConfig()
    env = cb_env.HostEnvironment(self.mock_runner, config,
                                 cb_env.ValidationMode.SKIP)
    env.handle_warning("foo")

  def test_warn_mode_fail(self):
    config = cb_env.HostEnvironmentConfig()
    env = cb_env.HostEnvironment(self.mock_runner, config,
                                 cb_env.ValidationMode.THROW)
    with self.assertRaises(cb_env.ValidationError) as cm:
      env.handle_warning("custom env check warning")
    self.assertIn("custom env check warning", str(cm.exception))

  def test_warn_mode_prompt(self):
    config = cb_env.HostEnvironmentConfig()
    env = cb_env.HostEnvironment(self.mock_runner, config,
                                 cb_env.ValidationMode.PROMPT)
    with mock.patch("builtins.input", return_value="Y") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])
    with mock.patch("builtins.input", return_value="n") as cm:
      with self.assertRaises(cb_env.ValidationError):
        env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_warn_mode_warn(self):
    config = cb_env.HostEnvironmentConfig()
    env = cb_env.HostEnvironment(self.mock_runner, config,
                                 cb_env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_validate_skip(self):
    env = cb_env.HostEnvironment(self.mock_runner,
                                 cb_env.HostEnvironmentConfig(),
                                 cb_env.ValidationMode.SKIP)
    env.validate()

  def test_validate_warn(self):
    env = cb_env.HostEnvironment(self.mock_runner,
                                 cb_env.HostEnvironmentConfig(),
                                 cb_env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_not_called()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_validate_warn_no_probes(self):
    env = cb_env.HostEnvironment(
        self.mock_runner, cb_env.HostEnvironmentConfig(require_probes=True),
        cb_env.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_called_once()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_request_battery_power_on(self):
    env = cb_env.HostEnvironment(
        self.mock_runner, cb_env.HostEnvironmentConfig(power_use_battery=True),
        cb_env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    env.validate()

    self.mock_platform.is_battery_powered = False
    with self.assertRaises(Exception) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

  def test_request_battery_power_off(self):
    env = cb_env.HostEnvironment(
        self.mock_runner, cb_env.HostEnvironmentConfig(power_use_battery=False),
        cb_env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    with self.assertRaises(cb_env.ValidationError) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

    self.mock_platform.is_battery_powered = False
    env.validate()

  def test_request_battery_power_off_conflicting_probe(self):
    env = cb_env.HostEnvironment(
        self.mock_runner, cb_env.HostEnvironmentConfig(power_use_battery=False),
        cb_env.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = False

    mock_probe = mock.Mock()
    mock_probe.configure_mock(BATTERY_ONLY=True, name="mock_probe")
    self.mock_runner.probes = [mock_probe]

    with self.assertRaises(cb_env.ValidationError) as cm:
      env.validate()
    message = str(cm.exception).lower()
    self.assertIn("mock_probe", message)
    self.assertIn("battery", message)

    mock_probe.BATTERY_ONLY = False
    env.validate()

  def test_request_is_headless_default(self):
    env = cb_env.HostEnvironment(
        self.mock_runner,
        cb_env.HostEnvironmentConfig(
            browser_is_headless=cb_env.HostEnvironmentConfig.Ignore),
        cb_env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    env.validate()

    mock_browser.is_headless = True
    env.validate()

  def test_request_is_headless_true(self):
    env = cb_env.HostEnvironment(
        self.mock_runner,
        cb_env.HostEnvironmentConfig(browser_is_headless=True),
        cb_env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    with self.assertRaises(cb_env.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))

    mock_browser.is_headless = True
    env.validate()

  def test_request_is_headless_false(self):
    env = cb_env.HostEnvironment(
        self.mock_runner,
        cb_env.HostEnvironmentConfig(browser_is_headless=False),
        cb_env.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    env.validate()

    mock_browser.is_headless = True
    with self.assertRaises(cb_env.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))
