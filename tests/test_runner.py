# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import crossbench as cb
from crossbench import runner


class ExceptionHandlerTestCase(unittest.TestCase):

  def test_empty(self):
    handler = runner.ExceptionHandler()
    self.assertTrue(handler.is_success)
    self.assertListEqual(handler.exceptions, [])
    self.assertListEqual(handler.to_json(), [])
    with mock.patch("logging.error") as logging_mock:
      handler.print()
    logging_mock.assert_called()

  def test_handle_exception(self):
    handler = runner.ExceptionHandler()
    exception = ValueError("custom message")
    try:
      raise exception
    except ValueError as e:
      handler.handle(e)
    self.assertFalse(handler.is_success)
    serialized = handler.to_json()
    self.assertEqual(len(serialized), 1)
    self.assertEqual(serialized[0]["title"], str(exception))
    with mock.patch("logging.error") as logging_mock:
      handler.print()
    logging_mock.assert_called_with(exception)

  def test_handle_rethrow(self):
    handler = runner.ExceptionHandler(throw=True)
    exception = ValueError("custom message")
    with self.assertRaises(ValueError) as cm:
      try:
        raise exception
      except ValueError as e:
        handler.handle(e)
    self.assertEqual(cm.exception, exception)
    self.assertFalse(handler.is_success)
    serialized = handler.to_json()
    self.assertEqual(len(serialized), 1)
    self.assertEqual(serialized[0]["title"], str(exception))

  def test_handle_keyboard_interrupt(self):
    handler = runner.ExceptionHandler()
    keyboard_interrupt = KeyboardInterrupt()
    with mock.patch("sys.exit", side_effect=ValueError) as exit_mock:
      with self.assertRaises(ValueError) as cm:
        try:
          raise keyboard_interrupt
        except KeyboardInterrupt as e:
          handler.handle(e)
      self.assertNotEqual(cm.exception, keyboard_interrupt)
    exit_mock.assert_called_once_with(0)

  def test_extend(self):
    handler_1 = runner.ExceptionHandler()
    try:
      raise ValueError("error_1")
    except ValueError as e:
      handler_1.handle(e)
    handler_2 = runner.ExceptionHandler()
    try:
      raise ValueError("error_2")
    except ValueError as e:
      handler_2.handle(e)
    handler_3 = runner.ExceptionHandler()
    handler_4 = runner.ExceptionHandler()
    self.assertFalse(handler_1.is_success)
    self.assertFalse(handler_2.is_success)
    self.assertTrue(handler_3.is_success)
    self.assertTrue(handler_4.is_success)

    self.assertEqual(len(handler_1.exceptions), 1)
    self.assertEqual(len(handler_2.exceptions), 1)
    handler_2.extend(handler_1)
    self.assertEqual(len(handler_2.exceptions), 2)
    self.assertFalse(handler_1.is_success)
    self.assertFalse(handler_2.is_success)

    self.assertEqual(len(handler_1.exceptions), 1)
    self.assertEqual(len(handler_3.exceptions), 0)
    self.assertEqual(len(handler_4.exceptions), 0)
    handler_3.extend(handler_1)
    handler_3.extend(handler_4)
    self.assertEqual(len(handler_3.exceptions), 1)
    self.assertFalse(handler_3.is_success)
    self.assertTrue(handler_4.is_success)


class HostEnvironmentTestCase(unittest.TestCase):

  def setUp(self):
    self.mock_platform = mock.Mock()
    self.mock_runner = mock.Mock(platform=self.mock_platform, probes=[])

  def test_instantiate(self):
    env = runner.HostEnvironment(self.mock_runner)
    self.assertEqual(env.runner, self.mock_runner)

    config = runner.HostEnvironmentConfig()
    env = runner.HostEnvironment(self.mock_runner, config)
    self.assertEqual(env.runner, self.mock_runner)
    self.assertEqual(env.config, config)

  def test_warn_mode_skip(self):
    config = runner.HostEnvironmentConfig()
    env = runner.HostEnvironment(self.mock_runner, config,
                                 runner.ValidationMode.SKIP)
    env.handle_warning("foo")

  def test_warn_mode_fail(self):
    config = runner.HostEnvironmentConfig()
    env = runner.HostEnvironment(self.mock_runner, config,
                                 runner.ValidationMode.THROW)
    with self.assertRaises(runner.ValidationError) as cm:
      env.handle_warning("custom env check warning")
    self.assertIn("custom env check warning", str(cm.exception))

  def test_warn_mode_prompt(self):
    config = runner.HostEnvironmentConfig()
    env = runner.HostEnvironment(self.mock_runner, config,
                                 runner.ValidationMode.PROMPT)
    with mock.patch("builtins.input", return_value="Y") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])
    with mock.patch("builtins.input", return_value="n") as cm:
      with self.assertRaises(runner.ValidationError):
        env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_warn_mode_warn(self):
    config = runner.HostEnvironmentConfig()
    env = runner.HostEnvironment(self.mock_runner, config,
                                 runner.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.handle_warning("custom env check warning")
    cm.assert_called_once()
    self.assertIn("custom env check warning", cm.call_args[0][0])

  def test_validate_skip(self):
    env = runner.HostEnvironment(self.mock_runner,
                                 runner.HostEnvironmentConfig(),
                                 runner.ValidationMode.SKIP)
    env.validate()

  def test_validate_warn(self):
    env = runner.HostEnvironment(self.mock_runner,
                                 runner.HostEnvironmentConfig(),
                                 runner.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_not_called()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_validate_warn_no_probes(self):
    env = runner.HostEnvironment(
        self.mock_runner, runner.HostEnvironmentConfig(require_probes=True),
        runner.ValidationMode.WARN)
    with mock.patch("logging.warn") as cm:
      env.validate()
    cm.assert_called_once()
    self.mock_platform.sh_stdout.assert_not_called()
    self.mock_platform.sh.assert_not_called()

  def test_request_battery_power_on(self):
    env = runner.HostEnvironment(
        self.mock_runner, runner.HostEnvironmentConfig(power_use_battery=True),
        runner.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    env.validate()

    self.mock_platform.is_battery_powered = False
    with self.assertRaises(Exception) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

  def test_request_battery_power_off(self):
    env = runner.HostEnvironment(
        self.mock_runner, runner.HostEnvironmentConfig(power_use_battery=False),
        runner.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = True
    with self.assertRaises(runner.ValidationError) as cm:
      env.validate()
    self.assertIn("battery", str(cm.exception).lower())

    self.mock_platform.is_battery_powered = False
    env.validate()

  def test_request_battery_power_off_conflicting_probe(self):
    env = runner.HostEnvironment(
        self.mock_runner, runner.HostEnvironmentConfig(power_use_battery=False),
        runner.ValidationMode.THROW)
    self.mock_platform.is_battery_powered = False

    mock_probe = mock.Mock()
    mock_probe.configure_mock(BATTERY_ONLY=True, name="mock_probe")
    self.mock_runner.probes = [mock_probe]

    with self.assertRaises(runner.ValidationError) as cm:
      env.validate()
    message = str(cm.exception).lower()
    self.assertIn("mock_probe", message)
    self.assertIn("battery", message)

    mock_probe.BATTERY_ONLY = False
    env.validate()

  def test_request_is_headless_default(self):
    env = runner.HostEnvironment(
        self.mock_runner,
        runner.HostEnvironmentConfig(
            browser_is_headless=runner.HostEnvironmentConfig.Ignore),
        runner.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    env.validate()

    mock_browser.is_headless = True
    env.validate()

  def test_request_is_headless_true(self):
    env = runner.HostEnvironment(
        self.mock_runner,
        runner.HostEnvironmentConfig(browser_is_headless=True),
        runner.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    with self.assertRaises(runner.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))

    mock_browser.is_headless = True
    env.validate()

  def test_request_is_headless_false(self):
    env = runner.HostEnvironment(
        self.mock_runner,
        runner.HostEnvironmentConfig(browser_is_headless=False),
        runner.ValidationMode.THROW)
    mock_browser = mock.Mock()
    self.mock_runner.browsers = [mock_browser]

    mock_browser.is_headless = False
    env.validate()

    mock_browser.is_headless = True
    with self.assertRaises(runner.ValidationError) as cm:
      env.validate()
    self.assertIn("is_headless", str(cm.exception))
