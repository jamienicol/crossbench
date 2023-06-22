# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import io
import json
import pathlib
import sys
import unittest
from typing import Dict, List, Tuple, Type
from unittest import mock

import hjson
import pytest
from pyfakefs import fake_filesystem_unittest

import crossbench
from crossbench import helper
from crossbench.browsers import splash_screen, viewport
from crossbench.browsers.chrome import Chrome, ChromeWebDriver
from crossbench.browsers.safari import Safari
from crossbench.cli import CrossBenchCLI
from crossbench.cli.cli_config import (BrowserConfig, BrowserVariantsConfig,
                                       BrowserDriverType, ConfigFileError,
                                       DriverConfig, FlagGroupConfig,
                                       ProbeConfig, ProbeConfigError)
from crossbench.probes.power_sampler import PowerSamplerProbe
from crossbench.probes.v8.log import V8LogProbe
from crossbench.runner import Runner
from tests.crossbench import mock_browser
from tests.crossbench.mock_helper import BaseCrossbenchTestCase, MockCLI


class SysExitException(Exception):

  def __init__(self, exit_code=0):
    super().__init__("sys.exit")
    self.exit_code = exit_code


class BrowserConfigTestCase(BaseCrossbenchTestCase):

  def test_parse_name_or_path(self):
    path = Chrome.stable_path()
    self.assertEqual(
        BrowserConfig.parse("chrome"),
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())))
    self.assertEqual(
        BrowserConfig.parse(str(path)),
        BrowserConfig(path, DriverConfig(BrowserDriverType.default())))

  def test_parse_invalid_name_or_path(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = BrowserConfig.parse("foo/bar")
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = BrowserConfig.parse("selenium/bar")

  def test_parse_simple_with_driver(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      _ = BrowserConfig.parse(":chrome")

    self.assertEqual(
        BrowserConfig.parse("selenium:chrome"),
        BrowserConfig(Chrome.stable_path(),
                      DriverConfig(BrowserDriverType.WEB_DRIVER)))
    self.assertEqual(
        BrowserConfig.parse("webdriver:chrome"),
        BrowserConfig(Chrome.stable_path(),
                      DriverConfig(BrowserDriverType.WEB_DRIVER)))
    self.assertEqual(
        BrowserConfig.parse("applescript:chrome"),
        BrowserConfig(Chrome.stable_path(),
                      DriverConfig(BrowserDriverType.APPLE_SCRIPT)))
    self.assertEqual(
        BrowserConfig.parse("osa:chrome"),
        BrowserConfig(Chrome.stable_path(),
                      DriverConfig(BrowserDriverType.APPLE_SCRIPT)))

  def test_parse_simple_with_driver_ios(self):
    self.assertEqual(
        BrowserConfig.parse("ios:chrome"),
        BrowserConfig(Chrome.stable_path(),
                      DriverConfig(BrowserDriverType.IOS)))

  def test_parse_simple_with_driver_android(self):
    self.assertEqual(
        BrowserConfig.parse("adb:chrome"),
        BrowserConfig(
            pathlib.Path("com.android.chrome"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertEqual(
        BrowserConfig.parse("adb:chrome-dev"),
        BrowserConfig(
            pathlib.Path("com.chrome.dev"),
            DriverConfig(BrowserDriverType.ANDROID)))
    self.assertEqual(
        BrowserConfig.parse("android:chrome-canary"),
        BrowserConfig(
            pathlib.Path("com.chrome.canary"),
            DriverConfig(BrowserDriverType.ANDROID)))

  @unittest.expectedFailure
  def test_parse_inline_config_simple(self):
    self.assertEqual(
        BrowserConfig.parse("adb:pixel_7:chrome"),
        BrowserConfig("android:chrome-canary",
                      DriverConfig(BrowserDriverType.ANDROID)))

  def test_parse_invalid_driver(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      BrowserConfig.parse("____:chrome")
    with self.assertRaises(argparse.ArgumentTypeError):
      # This has to be dealt with in users of DriverConfig.parse.
      BrowserConfig.parse("::chrome")


class CliTestCase(BaseCrossbenchTestCase):

  def run_cli(self, *args, raises=None) -> Tuple[MockCLI, str, str]:
    cli = MockCLI()
    with mock.patch(
        "sys.stdout", new_callable=io.StringIO) as mock_stdout, mock.patch(
            "sys.stderr", new_callable=io.StringIO) as mock_stderr, mock.patch(
                "sys.exit", side_effect=SysExitException):
      if raises:
        with self.assertRaises(raises):
          cli.run(args)
      else:
        cli.run(args)
    return cli, mock_stdout.getvalue(), mock_stderr.getvalue()

  def test_invalid(self):
    with self.assertRaises(SysExitException):
      self.run_cli("unknown subcommand", "--invalid flag")

  def test_describe_invalid(self):
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("describe", "")
    self.assertEqual(cm.exception.exit_code, 0)
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("describe", "--unknown")
    self.assertEqual(cm.exception.exit_code, 0)
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("describe", "probe", "unknown probe")
    self.assertEqual(cm.exception.exit_code, 0)
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("describe", "benchmark", "unknown benchmark")
    self.assertEqual(cm.exception.exit_code, 0)
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("describe", "all", "unknown probe")
    self.assertEqual(cm.exception.exit_code, 0)

  def test_describe(self):
    # Non-json output shouldn't fail
    self.run_cli("describe")
    self.run_cli("describe", "all")
    _, stdout, stderr = self.run_cli("describe", "--json")
    self.assertFalse(stderr)
    data = json.loads(stdout)
    self.assertIn("benchmarks", data)
    self.assertIn("probes", data)
    self.assertIsInstance(data["benchmarks"], dict)
    self.assertIsInstance(data["probes"], dict)

  def test_describe_benchmarks(self):
    # Non-json output shouldn't fail
    self.run_cli("describe", "benchmarks")
    _, stdout, stderr = self.run_cli("describe", "--json", "benchmarks")
    self.assertFalse(stderr)
    data = json.loads(stdout)
    self.assertNotIn("benchmarks", data)
    self.assertNotIn("probes", data)
    self.assertIsInstance(data, dict)
    self.assertIn("loading", data)

  def test_describe_probes(self):
    # Non-json output shouldn't fail
    self.run_cli("describe", "probes")
    _, stdout, stderr = self.run_cli("describe", "--json", "probes")
    self.assertFalse(stderr)
    data = json.loads(stdout)
    self.assertNotIn("benchmarks", data)
    self.assertNotIn("probes", data)
    self.assertIsInstance(data, dict)
    self.assertIn("v8.log", data)

  def test_help(self):
    with self.assertRaises(SysExitException) as cm:
      self.run_cli("--help")
    self.assertEqual(cm.exception.exit_code, 0)
    _, stdout, stderr = self.run_cli("--help", raises=SysExitException)
    self.assertFalse(stderr)
    self.assertGreater(len(stdout), 0)

  def test_help_subcommand(self):
    for benchmark_cls, aliases in CrossBenchCLI.BENCHMARKS:
      subcommands = (benchmark_cls.NAME,) + aliases
      for subcommand in subcommands:
        with self.assertRaises(SysExitException) as cm:
          self.run_cli(subcommand, "--help")
        self.assertEqual(cm.exception.exit_code, 0)
        _, stdout, stderr = self.run_cli(
            subcommand, "--help", raises=SysExitException)
        self.assertFalse(stderr)
        self.assertGreater(len(stdout), 0)

  def test_invalid_probe(self):
    with self.assertRaises(ProbeConfigError), mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--probe=invalid_probe_name", "--throw")

  def test_basic_probe_setting(self):
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", "--probe=v8.log", f"--urls={url}",
                   "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        self.assertIn("--log-all", browser.js_flags)

  def test_invalid_empty_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_file.touch()
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      with self.assertRaises(argparse.ArgumentError) as cm:
        self.run_cli("loading", f"--probe-config={config_file}",
                     f"--urls={url}", "--env-validation=skip", "--throw")
      message = str(cm.exception)
      self.assertIn("--probe-config", message)
      self.assertIn("empty", message)
      for browser in self.browsers:
        self.assertListEqual([], browser.url_list[1:])
        self.assertNotIn("--log", browser.js_flags)

  def test_empty_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe-config={config_file}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        self.assertNotIn("--log", browser.js_flags)

  def test_invalid_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {"invalid probe name": {}}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      with self.assertRaises(ProbeConfigError):
        self.run_cli("loading", f"--probe-config={config_file}",
                     f"--urls={url}", "--env-validation=skip", "--throw")
      for browser in self.browsers:
        self.assertListEqual([], browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    js_flags = ["--log-foo", "--log-bar"]
    config_data = {"probes": {"v8.log": {"js_flags": js_flags}}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)

    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe-config={config_file}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_probe_config_file_invalid_probe(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {"invalid probe name": {}}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with self.assertRaises(ProbeConfigError) as cm:
      with mock.patch.object(
          CrossBenchCLI, "_get_browsers", return_value=self.browsers):
        self.run_cli("loading", f"--probe-config={config_file}",
                     "--urls=http://test.com", "--env-validation=skip",
                     "--throw")
    self.assertIn("invalid probe name", str(cm.exception))

  def test_invalid_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {}, "browsers": {}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      with mock.patch.object(
          CrossBenchCLI, "_get_browsers", return_value=self.browsers):
        url = "http://test.com"
        self.run_cli("loading", f"--config={config_file}", f"--urls={url}",
                     "--env-validation=skip", "--throw")
    self.assertIn("env", str(cm.exception))

  def test_empty_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {}, "env": {}, "browsers": {}}
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--config={config_file}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        self.assertNotIn("--log", browser.js_flags)

  def test_config_file_with_probe(self):
    config_file = pathlib.Path("/config.hjson")
    js_flags = ["--log-foo", "--log-bar"]
    config_data = {
        "probes": {
            "v8.log": {
                "js_flags": js_flags
            }
        },
        "env": {},
        "browsers": {}
    }
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)

    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--config={config_file}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_invalid_browser_identifier(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", "--browser=unknown_browser_identifier",
                   "--urls=http://test.com", "--env-validation=skip", "--throw")
    self.assertIn("--browser", str(cm.exception))
    self.assertIn("unknown_browser_identifier", str(cm.exception))

  def test_unknown_browser_binary(self):
    browser_bin = pathlib.Path("/foo/custom/browser.bin")
    browser_bin.parent.mkdir(parents=True)
    browser_bin.touch()
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--env-validation=skip", "--throw")
    self.assertIn("--browser", str(cm.exception))
    self.assertIn(str(browser_bin), str(cm.exception))

  def test_custom_chrome_browser_binary(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    # TODO: migrate to with_stem once python 3.9 is available everywhere
    suffix = browser_cls.APP_PATH.suffix
    browser_bin = browser_cls.APP_PATH.with_name(
        f"Custom Google Chrome{suffix}")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")

    with mock.patch.object(
        BrowserVariantsConfig, "_get_browser_cls",
        return_value=browser_cls) as get_browser_cls:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--env-validation=skip")
    get_browser_cls.assert_called_once_with(
        BrowserConfig(browser_bin, DriverConfig.default()))

  def test_custom_chrome_browser_binary_custom_flags(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    # TODO: migrate to with_stem once python 3.9 is available everywhere
    suffix = browser_cls.APP_PATH.suffix
    browser_bin = browser_cls.APP_PATH.with_name(
        f"Custom Google Chrome{suffix}")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")

    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls", return_value=browser_cls), mock.patch.object(
            CrossBenchCLI, "_run_benchmark") as run_benchmark:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--env-validation=skip", "--",
                   "--chrome-flag1=value1", "--chrome-flag2")
    run_benchmark.assert_called_once()
    runner = run_benchmark.call_args[0][1]
    self.assertIsInstance(runner, Runner)
    self.assertEqual(len(runner.browsers), 1)
    browser = runner.browsers[0]
    self.assertListEqual(["--chrome-flag1=value1", "--chrome-flag2"],
                         list(browser.flags.get_list()))

  def test_browser_identifiers(self):
    browsers: Dict[str, Type[mock_browser.MockBrowser]] = {
        "chrome": mock_browser.MockChromeStable,
        "chrome-stable": mock_browser.MockChromeStable,
        "chr-stable": mock_browser.MockChromeStable,
        "chrome-beta": mock_browser.MockChromeBeta,
        "chr-beta": mock_browser.MockChromeBeta,
        "chrome-dev": mock_browser.MockChromeDev,
        "edge": mock_browser.MockEdgeStable,
        "edge-stable": mock_browser.MockEdgeStable,
        "edge-beta": mock_browser.MockEdgeBeta,
        "edge-dev": mock_browser.MockEdgeDev,
        "ff": mock_browser.MockFirefox,
        "firefox": mock_browser.MockFirefox,
        "firefox-dev": mock_browser.MockFirefoxDeveloperEdition,
        "firefox-developer-edition": mock_browser.MockFirefoxDeveloperEdition,
        "ff-dev": mock_browser.MockFirefoxDeveloperEdition,
        "firefox-nightly": mock_browser.MockFirefoxNightly,
        "ff-nightly": mock_browser.MockFirefoxNightly,
        "ff-trunk": mock_browser.MockFirefoxNightly,
    }
    if not self.platform.is_linux:
      browsers["chr-canary"] = mock_browser.MockChromeCanary
      browsers["chrome-canary"] = mock_browser.MockChromeCanary
      browsers["edge-canary"] = mock_browser.MockEdgeCanary
    if self.platform.is_macos:
      browsers.update({
          "safari": mock_browser.MockSafari,
          "sf": mock_browser.MockSafari,
          "safari-technology-preview": mock_browser.MockSafariTechnologyPreview,
          "sf-tp": mock_browser.MockSafariTechnologyPreview,
          "tp": mock_browser.MockSafariTechnologyPreview,
      })

    for identifier, browser_cls in browsers.items():
      out_dir = self.out_dir / identifier
      self.assertFalse(out_dir.exists())
      with mock.patch.object(
          BrowserVariantsConfig, "_get_browser_cls",
          return_value=browser_cls) as get_browser_cls:
        url = "http://test.com"
        self.run_cli("loading", f"--browser={identifier}", f"--urls={url}",
                     "--env-validation=skip", f"--out-dir={out_dir}")
        self.assertTrue(out_dir.exists())
        get_browser_cls.assert_called_once()
        result_file = list(out_dir.glob("**/results.json"))[0]
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        self.assertEqual(results["browser"]["version"], browser_cls.VERSION)
        self.assertIn("test.com", results["stories"])

  def test_browser_identifiers_duplicate(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      self.run_cli("loading", "--browser=chrome", "--browser=chrome",
                   "--urls=http://test.com", "--env-validation=skip", "--throw")

  def test_browser_identifiers_multiple(self):
    mock_browsers: List[Type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockChromeBeta,
        mock_browser.MockChromeDev,
    ]

    def mock_get_browser_cls(browser_config: BrowserConfig):
      self.assertEqual(browser_config.driver.type, BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.APP_PATH == browser_config.path:
          return mock_browser_cls
      raise ValueError("Unknown browser path")

    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        side_effect=mock_get_browser_cls) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-beta",
                   "--browser=chrome-stable", "--browser=chrome-dev",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      result_files = list(self.out_dir.glob("*/results.json"))
      self.assertEqual(len(result_files), 3)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 3)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_identifiers_multiple_same_major_version(self):

    class MockChromeBeta2(mock_browser.MockChromeBeta):
      VERSION = "100.22.33.100"

    class MockChromeDev2(mock_browser.MockChromeDev):
      VERSION = "100.22.33.200"

    mock_browsers: List[Type[mock_browser.MockBrowser]] = [
        MockChromeBeta2,
        MockChromeDev2,
    ]

    def mock_get_browser_cls(browser_config: BrowserConfig):
      self.assertEqual(browser_config.driver.type, BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.APP_PATH == browser_config.path:
          return mock_browser_cls
      raise ValueError("Unknown browser path")

    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        side_effect=mock_get_browser_cls) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-dev", "--browser=chrome-beta",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      result_files = list(self.out_dir.glob("*/results.json"))
      self.assertEqual(len(result_files), 2)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 2)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_identifiers_multiple_same_version(self):

    class MockChromeBeta2(mock_browser.MockChromeBeta):
      VERSION = "100.22.33.999"

    class MockChromeDev2(mock_browser.MockChromeDev):
      VERSION = "100.22.33.999"

    mock_browsers: List[Type[mock_browser.MockBrowser]] = [
        MockChromeBeta2,
        MockChromeDev2,
    ]

    def mock_get_browser_cls(browser_config: BrowserConfig):
      self.assertEqual(browser_config.driver.type, BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.APP_PATH == browser_config.path:
          return mock_browser_cls
      raise ValueError("Unknown browser path")

    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        side_effect=mock_get_browser_cls) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=chrome-dev", "--browser=chrome-beta",
                   f"--urls={url}", "--env-validation=skip",
                   f"--out-dir={self.out_dir}")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      result_files = list(self.out_dir.glob("*/results.json"))
      self.assertEqual(len(result_files), 2)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 1)
      for mock_browser_cls in mock_browsers:
        self.assertIn(mock_browser_cls.VERSION, versions)

  def test_browser_different_drivers(self):

    def mock_get_browser_cls(browser_config: BrowserConfig):
      if browser_config.driver.type == BrowserDriverType.IOS:
        self.assertEqual(browser_config.path,
                         mock_browser.MockChromeStable.APP_PATH)
        return mock_browser.MockChromeStable
      if browser_config.driver.type == BrowserDriverType.WEB_DRIVER:
        self.assertEqual(browser_config.path,
                         mock_browser.MockChromeBeta.APP_PATH)
        return mock_browser.MockChromeBeta
      self.assertEqual(browser_config.driver.type,
                       BrowserDriverType.APPLE_SCRIPT)
      self.assertEqual(browser_config.path, mock_browser.MockChromeDev.APP_PATH)
      return mock_browser.MockChromeDev

    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        side_effect=mock_get_browser_cls) as get_browser_cls:
      url = "http://test.com"
      self.run_cli("loading", "--browser=ios:chrome-stable",
                   "--browser=selenium:chrome-beta",
                   "--browser=applescript:chrome-dev", f"--urls={url}",
                   "--env-validation=skip", f"--out-dir={self.out_dir}")
      self.assertTrue(self.out_dir.exists())
      get_browser_cls.assert_called()
      result_files = list(self.out_dir.glob("*/results.json"))
      self.assertEqual(len(result_files), 3)
      versions = []
      for result_file in result_files:
        with result_file.open(encoding="utf-8") as f:
          results = json.load(f)
        versions.append(results["browser"]["version"])
        self.assertIn("test.com", results["stories"])
      self.assertTrue(len(set(versions)), 1)
      self.assertIn(mock_browser.MockChromeStable.VERSION, versions)
      self.assertIn(mock_browser.MockChromeBeta.VERSION, versions)
      self.assertIn(mock_browser.MockChromeDev.VERSION, versions)

  def test_probe_invalid_inline_json_config(self):
    with self.assertRaises(ProbeConfigError), mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--probe=v8.log{invalid json: d a t a}",
                   "--urls=cnn", "--env-validation=skip", "--throw")

  def test_probe_empty_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", "--probe=v8.log{}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        for flag in js_flags:
          self.assertNotIn(flag, browser.js_flags)

  def test_probe_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    json_config = json.dumps({"js_flags": js_flags})
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe=v8.log{json_config}", f"--urls={url}",
                   "--env-validation=skip")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list[1:])
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_env_config_name(self):
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--env=strict", "--urls=http://test.com",
                   "--env-validation=skip")

  def test_env_config_inline_hjson(self):
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--env={\"power_use_battery\":false}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_env_config_inline_invalid(self):
    with self.assertRaises(SysExitException):
      self.run_cli("loading", "--env=not a valid name",
                   "--urls=http://test.com", "--env-validation=skip")
    with self.assertRaises(SysExitException):
      self.run_cli("loading", "--env={not valid hjson}",
                   "--urls=http://test.com", "--env-validation=skip")
    with self.assertRaises(SysExitException):
      self.run_cli("loading", "--env={unknown_property:1}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_env_config_invalid_file(self):
    config = pathlib.Path("/test.config.hjson")
    # No "env" property
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({}, f)
    with self.assertRaises(SysExitException):
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")
    # "env" not a dict
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": []}, f)
    with self.assertRaises(SysExitException):
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": {"unknown_property_name": 1}}, f)
    with self.assertRaises(SysExitException):
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_multiple_browser_compatible_flags(self):
    mock_browsers: List[Type[mock_browser.MockBrowser]] = [
        mock_browser.MockChromeStable,
        mock_browser.MockFirefox,
        mock_browser.MockChromeDev,
    ]

    def mock_get_browser_cls(browser_config: BrowserConfig):
      self.assertEqual(browser_config.driver.type, BrowserDriverType.WEB_DRIVER)
      for mock_browser_cls in mock_browsers:
        if mock_browser_cls.APP_PATH == browser_config.path:
          return mock_browser_cls
      raise ValueError("Unknown browser path")

    for chrome_flag in ("--js-flags=--no-opt", "--enable-features=Foo",
                        "--disable-features=bar"):
      # Fail for chrome flags for non-chrome browser
      with self.assertRaises(argparse.ArgumentTypeError), mock.patch.object(
          BrowserVariantsConfig,
          "_get_browser_cls",
          side_effect=mock_get_browser_cls):
        self.run_cli("loading", "--urls=http://test.com",
                     "--env-validation=skip", "--throw", "--browser=firefox",
                     chrome_flag)
      # Fail for mixed browsers and chrome flags
      with self.assertRaises(argparse.ArgumentTypeError), mock.patch.object(
          BrowserVariantsConfig,
          "_get_browser_cls",
          side_effect=mock_get_browser_cls):
        self.run_cli("loading", "--urls=http://test.com",
                     "--env-validation=skip", "--throw", "--browser=chrome",
                     "--browser=firefox", chrome_flag)
      with self.assertRaises(argparse.ArgumentTypeError), mock.patch.object(
          BrowserVariantsConfig,
          "_get_browser_cls",
          side_effect=mock_get_browser_cls):
        self.run_cli("loading", "--urls=http://test.com",
                     "--env-validation=skip", "--throw", "--browser=chrome",
                     "--browser=firefox", "--", chrome_flag)
    # Flags for the same type are allowed.
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--urls=http://test.com", "--env-validation=skip",
                   "--throw", "--browser=chrome", "--browser=chrome-dev", "--",
                   "--js-flags=--no-opt")

  def test_parse_env_config_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": {}}, f)
    with mock.patch.object(
        CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_env_invalid_inline_and_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w", encoding="utf-8") as f:
      hjson.dump({"env": {}}, f)
    with self.assertRaises(SysExitException):
      self.run_cli("loading", "--env=strict", f"--env-config={config}",
                   "--urls=http://test.com", "--env-validation=skip")

  def test_invalid_splashscreen(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", "--browser=chrome", "--urls=http://test.com",
                   "--env-validation=skip", "--splash-screen=unknown-value",
                   "--throw")
    message = str(cm.exception)
    self.assertIn("--splash-screen", message)
    self.assertIn("unknown-value", message)

  def test_splash_screen_none(self):
    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        return_value=mock_browser.MockChromeStable):
      url = "http://test.com"
      cli, _, _ = self.run_cli("loading", f"--urls={url}",
                               "--env-validation=skip", "--throw",
                               "--splash-screen=none")
      for browser in cli.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.splash_screen, splash_screen.SplashScreen.NONE)
        self.assertListEqual([url], browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_splash_screen_minimal(self):
    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        return_value=mock_browser.MockChromeStable):
      url = "http://test.com"
      cli, _, _ = self.run_cli("loading", f"--urls={url}",
                               "--env-validation=skip", "--throw",
                               "--splash-screen=minimal")
      for browser in cli.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.splash_screen,
                         splash_screen.SplashScreen.MINIMAL)
        self.assertEqual(len(browser.url_list), 2)
        self.assertIn(url, browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_splash_screen_url(self):
    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        return_value=mock_browser.MockChromeStable):
      splash_url = "http://splash.com"
      url = "http://test.com"
      cli, _, _ = self.run_cli("loading", f"--urls={url}",
                               "--env-validation=skip", "--throw",
                               f"--splash-screen={splash_url}")
      for browser in cli.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertIsInstance(browser.splash_screen,
                              splash_screen.URLSplashScreen)
        self.assertEqual(len(browser.url_list), 2)
        self.assertEqual(splash_url, browser.url_list[0])
        self.assertEqual(len(browser.js_flags), 0)

  def test_viewport_invalid(self):
    with self.assertRaises(argparse.ArgumentError) as cm:
      self.run_cli("loading", "--browser=chrome", "--urls=http://test.com",
                   "--env-validation=skip", "--viewport=-123", "--throw")
    message = str(cm.exception)
    self.assertIn("--viewport", message)
    self.assertIn("-123", message)

  def test_viewport_maximized(self):
    with mock.patch.object(
        BrowserVariantsConfig,
        "_get_browser_cls",
        return_value=mock_browser.MockChromeStable):
      url = "http://test.com"
      cli, _, _ = self.run_cli("loading", f"--urls={url}",
                               "--env-validation=skip", "--throw",
                               "--viewport=maximized")
      for browser in cli.runner.browsers:
        assert isinstance(browser, mock_browser.MockChromeStable)
        self.assertEqual(browser.viewport, viewport.Viewport.MAXIMIZED)
        self.assertEqual(len(browser.url_list), 2)
        self.assertEqual(len(browser.js_flags), 0)


class TestProbeConfig(fake_filesystem_unittest.TestCase):
  # pylint: disable=expression-not-assigned

  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[crossbench, mock_browser])

  def parse_config(self, config_data) -> ProbeConfig:
    probe_config_file = pathlib.Path("/probe.config.hjson")
    with probe_config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    with probe_config_file.open(encoding="utf-8") as f:
      return ProbeConfig.load(f)

  def test_invalid_empty(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      self.parse_config({}).probes
    with self.assertRaises(argparse.ArgumentTypeError):
      self.parse_config({"foo": {}}).probes

  def test_invalid_names(self):
    with self.assertRaises(argparse.ArgumentTypeError):
      self.parse_config({"probes": {"invalid probe name": {}}}).probes

  def test_empty(self):
    config = self.parse_config({"probes": {}})
    self.assertListEqual(config.probes, [])

  def test_single_v8_log(self):
    js_flags = ["--log-maps", "--log-function-events"]
    config = self.parse_config(
        {"probes": {
            "v8.log": {
                "prof": True,
                "js_flags": js_flags,
            }
        }})
    self.assertTrue(len(config.probes), 1)
    probe = config.probes[0]
    assert isinstance(probe, V8LogProbe)
    for flag in js_flags + ["--prof"]:
      self.assertIn(flag, probe.js_flags)

  def test_from_cli_args(self):
    file = pathlib.Path("probe.config.hjson")
    js_flags = ["--log-maps", "--log-function-events"]
    config_data = {
        "probes": {
            "v8.log": {
                "prof": True,
                "js_flags": js_flags,
            }
        }
    }
    with file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)
    args = mock.Mock(probe_config=file)
    config = ProbeConfig.from_cli_args(args)
    self.assertTrue(len(config.probes), 1)
    probe = config.probes[0]
    assert isinstance(probe, V8LogProbe)
    for flag in js_flags + ["--prof"]:
      self.assertIn(flag, probe.js_flags)

  def test_inline_config(self):
    mock_d8_file = pathlib.Path("out/d8")
    self.fs.create_file(mock_d8_file, st_size=8 * 1024)
    config_data = {"d8_binary": str(mock_d8_file)}
    args = mock.Mock(probe_config=None, throw=True, wraps=False)

    args.probe = [
        f"v8.log{hjson.dumps(config_data)}",
    ]
    config = ProbeConfig.from_cli_args(args)
    self.assertTrue(len(config.probes), 1)
    probe = config.probes[0]
    self.assertTrue(isinstance(probe, V8LogProbe))

    args.probe = [
        f"v8.log:{hjson.dumps(config_data)}",
    ]
    config = ProbeConfig.from_cli_args(args)
    self.assertTrue(len(config.probes), 1)
    probe = config.probes[0]
    self.assertTrue(isinstance(probe, V8LogProbe))

  def test_inline_config_invalid(self):
    mock_d8_file = pathlib.Path("out/d8")
    self.fs.create_file(mock_d8_file)
    config_data = {"d8_binary": str(mock_d8_file)}
    args = mock.Mock(probe_config=None, throw=True, wraps=False)
    trailing_brace = "}"
    args.probe = [
        f"v8.log{hjson.dumps(config_data)}{trailing_brace}",
    ]
    with self.assertRaises(ProbeConfigError):
      ProbeConfig.from_cli_args(args)
    args.probe = [
        f"v8.log:{hjson.dumps(config_data)}{trailing_brace}",
    ]
    with self.assertRaises(ProbeConfigError):
      ProbeConfig.from_cli_args(args)
    args.probe = [
        "v8.log::",
    ]
    with self.assertRaises(ProbeConfigError):
      ProbeConfig.from_cli_args(args)

  def test_inline_config_dir_instead_of_file(self):
    mock_dir = pathlib.Path("some/dir")
    mock_dir.mkdir(parents=True)
    config_data = {"d8_binary": str(mock_dir)}
    args = mock.Mock(
        probe=[f"v8.log{hjson.dumps(config_data)}"],
        probe_config=None,
        throw=True,
        wraps=False)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ProbeConfig.from_cli_args(args)
    self.assertIn(str(mock_dir), str(cm.exception))

  def test_inline_config_non_existent_file(self):
    config_data = {"d8_binary": "does/not/exist/d8"}
    args = mock.Mock(
        probe=[f"v8.log{hjson.dumps(config_data)}"],
        probe_config=None,
        throw=True,
        wraps=False)
    with self.assertRaises(argparse.ArgumentTypeError) as cm:
      ProbeConfig.from_cli_args(args)
    expected_path = pathlib.Path("does/not/exist/d8")
    self.assertIn(str(expected_path), str(cm.exception))

  def test_multiple_probes(self):
    powersampler_bin = pathlib.Path("/powersampler.bin")
    powersampler_bin.touch()
    config = self.parse_config({
        "probes": {
            "v8.log": {
                "log_all": True,
            },
            "powersampler": {
                "bin_path": str(powersampler_bin)
            }
        }
    })
    self.assertTrue(len(config.probes), 2)
    log_probe = config.probes[0]
    assert isinstance(log_probe, V8LogProbe)
    powersampler_probe = config.probes[1]
    assert isinstance(powersampler_probe, PowerSamplerProbe)
    self.assertEqual(powersampler_probe.bin_path, powersampler_bin)


class TestBrowserVariantsConfig(BaseCrossbenchTestCase):
  # pylint: disable=expression-not-assigned

  EXAMPLE_CONFIG_PATH = pathlib.Path(
      __file__).parent.parent / "config" / "browser.config.example.hjson"

  def setUp(self):
    super().setUp()
    self.browser_lookup: Dict[str, Tuple[
        Type[mock_browser.MockBrowser], BrowserConfig]] = {
            "chr-stable":
                (mock_browser.MockChromeStable,
                 BrowserConfig(mock_browser.MockChromeStable.APP_PATH)),
            "chr-dev": (mock_browser.MockChromeDev,
                        BrowserConfig(mock_browser.MockChromeDev.APP_PATH)),
            "chrome-stable":
                (mock_browser.MockChromeStable,
                 BrowserConfig(mock_browser.MockChromeStable.APP_PATH)),
            "chrome-dev": (mock_browser.MockChromeDev,
                           BrowserConfig(mock_browser.MockChromeDev.APP_PATH)),
        }
    for _, (_, browser_config) in self.browser_lookup.items():
      self.assertTrue(browser_config.path.exists())
    self.mock_args = mock.Mock(driver_path=None)

  @unittest.skipIf(hjson.__name__ != "hjson", "hjson not available")
  def test_load_browser_config_template(self):
    if not self.EXAMPLE_CONFIG_PATH.exists():
      raise unittest.SkipTest(
          f"Test file {self.EXAMPLE_CONFIG_PATH} does not exist")
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open(encoding="utf-8") as f:
      config = BrowserVariantsConfig(
          browser_lookup_override=self.browser_lookup)
      config.load(f, args=self.mock_args)
    self.assertIn("flag-group-1", config.flag_groups)
    self.assertGreaterEqual(len(config.flag_groups), 1)
    self.assertGreaterEqual(len(config.variants), 1)

  def test_flag_combination_invalid(self):
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {
                      "invalid-flag-name": [None, "", "v1"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1",]
                  }
              }
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args).variants
    message = str(cm.exception)
    self.assertIn("group1", message)
    self.assertIn("invalid-flag-name", message)

  def test_flag_combination_none(self):
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {
                      "--foo": ["None,", "", "v1"],
                  },
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1"]
                  }
              }
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args).variants
    self.assertIn("None", str(cm.exception))

  def test_flag_combination_duplicate(self):
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {
                      "--duplicate-flag": [None, "", "v1"],
                  },
                  "group2": {
                      "--duplicate-flag": [None, "", "v1"],
                  }
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1", "group2"]
                  }
              }
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args).variants
    self.assertIn("--duplicate-flag", str(cm.exception))

  def test_empty(self):
    with self.assertRaises(ConfigFileError):
      BrowserVariantsConfig({"other": {}}, args=self.mock_args).variants
    with self.assertRaises(ConfigFileError):
      BrowserVariantsConfig({"browsers": {}}, args=self.mock_args).variants

  def test_unknown_group(self):
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["unknown-flag-group"]
                  }
              }
          },
          args=self.mock_args).variants
    self.assertIn("unknown-flag-group", str(cm.exception))

  def test_duplicate_group(self):
    with self.assertRaises(ConfigFileError):
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {}
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": ["group1", "group1"]
                  }
              }
          },
          args=self.mock_args).variants

  def test_non_list_group(self):
    BrowserVariantsConfig(
        {
            "flags": {
                "group1": {}
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": "group1"
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args).variants
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {}
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": 1
                  }
              }
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args).variants
    self.assertIn("chrome-stable", str(cm.exception))
    self.assertIn("flags", str(cm.exception))

    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {}
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": {
                          "group1": True
                      }
                  }
              }
          },
          browser_lookup_override=self.browser_lookup,
          args=self.mock_args).variants
    self.assertIn("chrome-stable", str(cm.exception))
    self.assertIn("flags", str(cm.exception))

  def test_duplicate_flag_variant_value(self):
    with self.assertRaises(ConfigFileError) as cm:
      BrowserVariantsConfig(
          {
              "flags": {
                  "group1": {
                      "--flag": ["repeated", "repeated"]
                  }
              },
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-stable",
                      "flags": "group1",
                  }
              }
          },
          args=self.mock_args).variants
    self.assertIn("group1", str(cm.exception))
    self.assertIn("--flag", str(cm.exception))

  def test_unknown_path(self):
    with self.assertRaises(Exception):
      BrowserVariantsConfig(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "path/does/not/exist",
                  }
              }
          },
          args=self.mock_args).variants
    with self.assertRaises(Exception):
      BrowserVariantsConfig(
          {
              "browsers": {
                  "chrome-stable": {
                      "path": "chrome-unknown",
                  }
              }
          },
          args=self.mock_args).variants

  def test_flag_combination_simple(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                }
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    browsers = config.variants
    self.assertEqual(len(browsers), 3)
    for browser in browsers:
      assert isinstance(browser, mock_browser.MockChromeStable)
      self.assertDictEqual(dict(browser.js_flags), {})
    self.assertDictEqual(dict(browsers[0].flags), {})
    self.assertDictEqual(dict(browsers[1].flags), {"--foo": None})
    self.assertDictEqual(dict(browsers[2].flags), {"--foo": "v1"})

  def test_flag_combination(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                    "--bar": [None, "", "v1"],
                }
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    self.assertEqual(len(config.variants), 3 * 3)

  def test_flag_combination_mixed_inline(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "compile-hints-experiment": {
                    "--enable-features": [None, "ConsumeCompileHints"]
                }
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": ["--no-sandbox", "compile-hints-experiment"]
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    browsers = config.variants
    self.assertEqual(len(browsers), 2)
    self.assertListEqual(["--no-sandbox"], list(browsers[0].flags.get_list()))
    self.assertListEqual(
        ["--no-sandbox", "--enable-features=ConsumeCompileHints"],
        list(browsers[1].flags.get_list()))

  def test_flag_single_inline(self):
    config = BrowserVariantsConfig(
        {
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": "--no-sandbox",
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    browsers = config.variants
    self.assertEqual(len(browsers), 1)
    self.assertListEqual(["--no-sandbox"], list(browsers[0].flags.get_list()))

  def test_flag_combination_mixed_fixed(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "compile-hints-experiment": {
                    "--no-sandbox": "",
                    "--enable-features": [None, "ConsumeCompileHints"]
                }
            },
            "browsers": {
                "chrome-release": {
                    "path": "chrome-stable",
                    "flags": "compile-hints-experiment"
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    browsers = config.variants
    self.assertEqual(len(browsers), 2)
    self.assertListEqual(["--no-sandbox"], list(browsers[0].flags.get_list()))
    self.assertListEqual(
        ["--no-sandbox", "--enable-features=ConsumeCompileHints"],
        list(browsers[1].flags.get_list()))

  def test_no_flags(self):
    config = BrowserVariantsConfig(
        {
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                },
                "chrome-dev": {
                    "path": "chrome-dev",
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    self.assertEqual(len(config.variants), 2)
    browser_0 = config.variants[0]
    assert isinstance(browser_0, mock_browser.MockChromeStable)
    self.assertEqual(browser_0.app_path, mock_browser.MockChromeStable.APP_PATH)
    browser_1 = config.variants[1]
    assert isinstance(browser_1, mock_browser.MockChromeDev)
    self.assertEqual(browser_1.app_path, mock_browser.MockChromeDev.APP_PATH)

  def test_inline_flags(self):
    with mock.patch.object(
        ChromeWebDriver, "_extract_version",
        return_value="101.22.333.44"), mock.patch.object(
            Chrome,
            "stable_path",
            return_value=mock_browser.MockChromeStable.APP_PATH):

      config = BrowserVariantsConfig(
          {
              "browsers": {
                  "stable": {
                      "path": "chrome-stable",
                      "flags": ["--foo=bar"]
                  }
              }
          },
          args=self.mock_args)
      self.assertEqual(len(config.variants), 1)
      browser = config.variants[0]
      # TODO: Fix once app lookup is cleaned up
      self.assertEqual(browser.app_path, mock_browser.MockChromeStable.APP_PATH)
      self.assertEqual(browser.version, "101.22.333.44")

  def test_inline_load_safari(self):
    if not helper.PLATFORM.is_macos:
      return
    with mock.patch.object(Safari, "_extract_version", return_value="16.0"):
      config = BrowserVariantsConfig(
          {"browsers": {
              "safari": {
                  "path": "safari",
              }
          }}, args=self.mock_args)
      self.assertEqual(len(config.variants), 1)

  def test_flag_combination_with_fixed(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                    "--bar": [None, "", "v1"],
                    "--always_1": "true",
                    "--always_2": "true",
                    "--always_3": "true",
                }
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    self.assertEqual(len(config.variants), 3 * 3)
    for browser in config.variants:
      assert isinstance(browser, mock_browser.MockChromeStable)
      self.assertEqual(browser.app_path, mock_browser.MockChromeStable.APP_PATH)

  def test_flag_group_combination(self):
    config = BrowserVariantsConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                },
                "group2": {
                    "--bar": [None, "", "v1"],
                },
                "group3": {
                    "--other": ["v1", "v2"],
                }
            },
            "browsers": {
                "chrome-stable": {
                    "path": "chrome-stable",
                    "flags": ["group1", "group2", "group3"]
                }
            }
        },
        browser_lookup_override=self.browser_lookup,
        args=self.mock_args)
    self.assertEqual(len(config.variants), 3 * 3 * 2)

  def test_from_cli_args_browser_config(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    # TODO: migrate to with_stem once python 3.9 is available everywhere
    suffix = browser_cls.APP_PATH.suffix
    browser_bin = browser_cls.APP_PATH.with_name(
        f"Custom Google Chrome{suffix}")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")
    config_data = {"browsers": {"chrome-stable": {"path": str(browser_bin),}}}
    config_file = pathlib.Path("config.hjson")
    with config_file.open("w", encoding="utf-8") as f:
      hjson.dump(config_data, f)

    args = mock.Mock(browser=None, browser_config=config_file, driver_path=None)
    with mock.patch.object(
        BrowserVariantsConfig, "_get_browser_cls", return_value=browser_cls):
      config = BrowserVariantsConfig.from_cli_args(args)
    self.assertEqual(len(config.variants), 1)
    browser = config.variants[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.app_path, browser_bin)

  def test_from_cli_args_browser(self):
    if self.platform.is_win:
      self.skipTest("No auto-download available on windows")
    browser_cls = mock_browser.MockChromeStable
    # TODO: migrate to with_stem once python 3.9 is available everywhere
    suffix = browser_cls.APP_PATH.suffix
    browser_bin = browser_cls.APP_PATH.with_name(
        f"Custom Google Chrome{suffix}")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")
    args = mock.Mock(
        browser=[
            BrowserConfig(browser_bin),
        ],
        browser_config=None,
        enable_features=None,
        disable_features=None,
        driver_path=None,
        js_flags=None,
        other_browser_args=[])
    with mock.patch.object(
        BrowserVariantsConfig, "_get_browser_cls", return_value=browser_cls):
      config = BrowserVariantsConfig.from_cli_args(args)
    self.assertEqual(len(config.variants), 1)
    browser = config.variants[0]
    self.assertIsInstance(browser, browser_cls)
    self.assertEqual(browser.app_path, browser_bin)


class TestFlagGroupConfig(unittest.TestCase):

  def parse(self, config_dict):
    config = FlagGroupConfig("test", config_dict)
    variants = list(config.get_variant_items())
    return variants

  def test_empty(self):
    config = FlagGroupConfig("empty_name", {})
    self.assertEqual(config.name, "empty_name")
    variants = list(config.get_variant_items())
    self.assertEqual(len(variants), 0)

  def test_single_flag(self):
    variants = self.parse({"--foo": set()})
    self.assertListEqual(variants, [
        (),
    ])

    variants = self.parse({"--foo": []})
    self.assertListEqual(variants, [
        (),
    ])

    variants = self.parse({"--foo": (None,)})
    self.assertListEqual(variants, [
        (None,),
    ])

    variants = self.parse({"--foo": ("",)})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(
        variants[0],
        (("--foo", None),),
    )

    variants = self.parse({"--foo": (
        "",
        None,
    )})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(variants[0], (("--foo", None), None))

    variants = self.parse({"--foo": (
        "v1",
        "v2",
        "",
        None,
    )})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(variants[0], (("--foo", "v1"), ("--foo", "v2"),
                                        ("--foo", None), None))

  def test_two_flags(self):
    variants = self.parse({"--foo": [], "--bar": []})
    self.assertListEqual(variants, [(), ()])

    variants = self.parse({"--foo": "a", "--bar": "b"})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (("--foo", "a"),))
    self.assertTupleEqual(variants[1], (("--bar", "b"),))

    variants = self.parse({"--foo": ["a1", "a2"], "--bar": "b"})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (
        ("--foo", "a1"),
        ("--foo", "a2"),
    ))
    self.assertTupleEqual(variants[1], (("--bar", "b"),))

    variants = self.parse({"--foo": ["a1", "a2"], "--bar": ["b1", "b2"]})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (
        ("--foo", "a1"),
        ("--foo", "a2"),
    ))
    self.assertTupleEqual(variants[1], (
        ("--bar", "b1"),
        ("--bar", "b2"),
    ))


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
