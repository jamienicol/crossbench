# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import json
import pathlib
from typing import List
import unittest
import unittest.mock as mock

import pyfakefs.fake_filesystem_unittest

import crossbench as cb
from crossbench import helper
import crossbench.probes.all
import crossbench.cli

from tests import mockbenchmark


class SysExitException(Exception):

  def __init__(self):
    super().__init__("sys.exit")


class TestCLI(mockbenchmark.BaseCrossbenchTestCase):

  def run_cli(self, *args, raises=None):
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      cli = mockbenchmark.MockCLI()
      if raises:
        with self.assertRaises(raises):
          cli.run(args)
      else:
        cli.run(args)
      return cli, mock_stdout.getvalue()

  def test_invalid(self):
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      self.run_cli(
          "unknown subcommand", "--invalid flag", raises=SysExitException)

  def test_describe_invalid(self):
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      self.run_cli("describe", "", raises=SysExitException)
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      self.run_cli("describe", "--unknown", raises=SysExitException)

  def test_describe(self):
    # Non-json output shouldn't fail
    self.run_cli("describe")
    self.run_cli("describe", "all")
    cli, stdout = self.run_cli("describe", "--json")
    data = json.loads(stdout)
    self.assertIn("benchmarks", data)
    self.assertIn("probes", data)
    self.assertIsInstance(data["benchmarks"], dict)
    self.assertIsInstance(data["probes"], dict)

  def test_describe_benchmarks(self):
    # Non-json output shouldn't fail
    self.run_cli("describe", "benchmarks")
    cli, stdout = self.run_cli("describe", "--json", "benchmarks")
    data = json.loads(stdout)
    self.assertNotIn("benchmarks", data)
    self.assertNotIn("probes", data)
    self.assertIsInstance(data, dict)
    self.assertIn("loading", data)

  def test_describe_probes(self):
    # Non-json output shouldn't fail
    self.run_cli("describe", "probes")
    cli, stdout = self.run_cli("describe", "--json", "probes")
    data = json.loads(stdout)
    self.assertNotIn("benchmarks", data)
    self.assertNotIn("probes", data)
    self.assertIsInstance(data, dict)
    self.assertIn("v8.log", data)

  def test_help(self):
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      cli, stdout = self.run_cli("--help", raises=SysExitException)
      self.assertTrue(exit_mock.called)
      exit_mock.assert_called_with(0)
      self.assertGreater(len(stdout), 0)

  def test_help_subcommand(self):
    for benchmark_cls, aliases in cb.cli.CrossBenchCLI.BENCHMARKS:
      subcommands = (benchmark_cls.NAME,) + aliases
      for subcommand in subcommands:
        with mock.patch(
            "sys.exit", side_effect=SysExitException()) as exit_mock:
          stdout = self.run_cli(subcommand, "--help", raises=SysExitException)
          self.assertTrue(exit_mock.called)
          exit_mock.assert_called_with(0)
          self.assertGreater(len(stdout), 0)

  def test_invalid_probe(self):
    with (self.assertRaises(ValueError),
          mock.patch.object(
              cb.cli.CrossBenchCLI, "_get_browsers",
              return_value=self.browsers)):
      self.run_cli("loading", "--probe=invalid_probe_name")

  def test_basic_probe_setting(self):
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", "--probe=v8.log", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        self.assertIn("--log-all", browser.js_flags)

  def test_invalid_empty_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_file.touch()
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      with self.assertRaises(ValueError):
        self.run_cli("loading", f"--probe-config={config_file}",
                     f"--urls={url}", "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([], browser.url_list)
        self.assertNotIn("--log", browser.js_flags)

  def test_empty_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {}}
    with config_file.open("w") as f:
      json.dump(config_data, f)
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe-config={config_file}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        self.assertNotIn("--log", browser.js_flags)

  def test_invalid_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {"invalid probe name": {}}}
    with config_file.open("w") as f:
      json.dump(config_data, f)
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      with self.assertRaises(ValueError):
        self.run_cli("loading", f"--probe-config={config_file}",
                     f"--urls={url}", "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([], browser.url_list)
        self.assertEqual(len(browser.js_flags), 0)

  def test_probe_config_file(self):
    config_file = pathlib.Path("/config.hjson")
    js_flags = ["--log-foo", "--log-bar"]
    config_data = {"probes": {"v8.log": {"js_flags": js_flags}}}
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(config_data, f)

    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe-config={config_file}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_probe_config_file_invalid_probe(self):
    config_file = pathlib.Path("/config.hjson")
    config_data = {"probes": {"invalid probe name": {}}}
    with config_file.open("w", encoding="utf-8") as f:
      json.dump(config_data, f)

    with (mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers",
        return_value=self.browsers), self.assertRaises(ValueError)):
      self.run_cli("loading", f"--probe-config={config_file}",
                   "--urls=http://test.com", "--skip-checklist")

  def test_invalid_browser_identifier(self):
    with self.assertRaises(ValueError):
      self.run_cli(
          "loading",
          "--browser=unknown_browser_identifier",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)

  def test_unknown_browser_binary(self):
    browser_bin = pathlib.Path("/foo/custom/browser.bin")
    browser_bin.parent.mkdir(parents=True)
    browser_bin.touch()
    with self.assertRaises(ValueError):
      self.run_cli(
          "loading",
          f"--browser={browser_bin}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)

  def test_custom_chrome_browser_binary(self):
    browser_cls = mockbenchmark.MockChromeStable
    browser_bin = browser_cls.APP_PATH.with_stem("Custom Google Chrome")
    browser_cls.setup_bin(self.fs, browser_bin, "Chrome")

    with mock.patch.object(
        cb.cli.BrowserConfig,
        "_get_browser_cls_from_path",
        return_value=browser_cls) as get_browser_cls:
      self.run_cli("loading", f"--browser={browser_bin}",
                   "--urls=http://test.com", "--skip-checklist")
      get_browser_cls.assert_called_once()

  def test_browser_ientifiers(self):
    browsers = {
        "chrome": mockbenchmark.MockChromeStable,
        "chrome stable": mockbenchmark.MockChromeStable,
        "stable": mockbenchmark.MockChromeStable,
        "chrome beta": mockbenchmark.MockChromeBeta,
        "beta": mockbenchmark.MockChromeBeta,
        "chrome dev": mockbenchmark.MockChromeDev,
        "canary": mockbenchmark.MockChromeCanary,
        "chrome canary": mockbenchmark.MockChromeCanary,
        # Not actually supported on other plaforms than macOs
        "safari": mockbenchmark.MockSafari,
        "tp": mockbenchmark.MockSafariTechnologyPreview,
        "safari technology preview": mockbenchmark.MockSafariTechnologyPreview,
    }

    for identifier, browser_cls in browsers.items():
      browser_cls = mockbenchmark.MockChromeStable
      out_dir = self.out_dir / identifier
      self.assertFalse(out_dir.exists())
      with mock.patch.object(
          cb.cli.BrowserConfig,
          "_get_browser_cls_from_path",
          return_value=browser_cls) as get_browser_cls:
        url = "http://test.com"
        cli, stdout = self.run_cli("loading", f"--browser={identifier}",
                                   f"--urls={url}", "--skip-checklist",
                                   f"--out-dir={out_dir}")
        self.assertTrue(out_dir.exists())
        get_browser_cls.assert_called_once()
        result_file = list(out_dir.glob("**/results.json"))[0]
        with result_file.open() as f:
          results = json.load(f)
        self.assertEqual(results["browser"]["version"], browser_cls.VERSION)
        self.assertIn("test.com", results["stories"])

  def test_probe_invalid_inline_json_config(self):
    with (self.assertRaises(ValueError),
          mock.patch.object(
              cb.cli.CrossBenchCLI, "_get_browsers",
              return_value=self.browsers)):
      self.run_cli("loading", "--probe=v8.log{invalid json: d a t a}",
                   f"--urls=cnn", "--skip-checklist")

  def test_probe_empty_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", "--probe=v8.log{}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        for flag in js_flags:
          self.assertNotIn(flag, browser.js_flags)

  def test_probe_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    json_config = json.dumps({"js_flags": js_flags})
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe=v8.log{json_config}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_env_config_name(self):
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--env=strict", "--urls=http://test.com",
                   "--skip-checklist")

  def test_env_config_inline_hjson(self):
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", "--env={power_use_battery:false}",
                   "--urls=http://test.com", "--skip-checklist")

  def test_env_config_inline_invalid(self):
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          "--env=not a valid name",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          "--env={not valid hjson}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          "--env={unknown_property:1}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)

  def test_env_config_invalid_file(self):
    config = pathlib.Path("/test.config.hjson")
    # No "env" property
    with config.open("w") as f:
      f.write("{}")
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          f"--env-config={config}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)
    # "env" not a dict
    with config.open("w") as f:
      f.write("{env:[]}")
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          f"--env-config={config}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)
    with config.open("w") as f:
      f.write("{env:{unknown_property_name:1}}")
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          f"--env-config={config}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)

  def test_env_config_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w") as f:
      f.write("{env:{}}")
    with mock.patch.object(
        cb.cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      self.run_cli("loading", f"--env-config={config}",
                   "--urls=http://test.com", "--skip-checklist")

  def test_env_invalid_inline_and_file(self):
    config = pathlib.Path("/test.config.hjson")
    with config.open("w") as f:
      f.write("{env:{}}")
    with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
      self.run_cli(
          "loading",
          "--env=strict",
          f"--env-config={config}",
          "--urls=http://test.com",
          "--skip-checklist",
          raises=SysExitException)


class TestProbeConfig(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])

  def parse_config(self, config_data) -> cb.cli.ProbeConfig:
    probe_config_file = pathlib.Path("/probe.config.hjson")
    with probe_config_file.open("w") as f:
      json.dump(config_data, f)
    with probe_config_file.open() as f:
      return cb.cli.ProbeConfig.load(f)

  def test_invalid_empty(self):
    with self.assertRaises(ValueError):
      self.parse_config({})
    with self.assertRaises(ValueError):
      self.parse_config({"foo": {}})

  def test_invalid_names(self):
    with self.assertRaises(ValueError):
      self.parse_config({"probes": {"invalid probe name": {}}})

  def test_empty(self):
    config = self.parse_config({"probes": {}})
    self.assertListEqual(config.probes, [])

  def test_single_c8_log(self):
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
    self.assertTrue(isinstance(probe, cb.probes.all.V8LogProbe))
    for flag in js_flags + ["--prof"]:
      self.assertIn(flag, probe.js_flags)

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
    self.assertTrue(isinstance(log_probe, cb.probes.all.V8LogProbe))
    powersampler_probe = config.probes[1]
    self.assertTrue(
        isinstance(powersampler_probe, cb.probes.all.PowerSamplerProbe))
    self.assertEqual(powersampler_probe.bin_path, powersampler_bin)


class TestBrowserConfig(mockbenchmark.BaseCrossbenchTestCase):
  EXAMPLE_CONFIG_PATH = pathlib.Path(
      __file__).parent.parent / "config" / "browser.config.example.hjson"

  def setUp(self):
    super().setUp()
    self.BROWSER_LOOKUP = {
        "stable": (mockbenchmark.MockChromeStable,
                   mockbenchmark.MockChromeStable.APP_PATH),
        "dev":
            (mockbenchmark.MockChromeDev, mockbenchmark.MockChromeDev.APP_PATH),
        "chrome-stable": (mockbenchmark.MockChromeStable,
                          mockbenchmark.MockChromeStable.APP_PATH),
        "chrome-dev":
            (mockbenchmark.MockChromeDev, mockbenchmark.MockChromeDev.APP_PATH),
    }

  def test_load_browser_config_template(self):
    if not self.EXAMPLE_CONFIG_PATH.exists():
      raise unittest.SkipTest(
          f"Test file {self.EXAMPLE_CONFIG_PATH} does not exist")
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open() as f:
      config = cb.cli.BrowserConfig.load(
          f, browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertIn("default", config.flag_groups)
    self.assertGreaterEqual(len(config.flag_groups), 1)
    self.assertGreaterEqual(len(config.variants), 1)

  def test_flag_combination_invalid(self):
    with self.assertRaises(Exception):
      cb.cli.BrowserConfig(
          {
              "flags": {
                  "group1": {
                      "invalidFlag": [None, "", "v1"],
                  },
              },
              "browsers": {
                  "stable": {
                      "path": "stable",
                      "flags": ["group1", "group2"]
                  }
              }
          },
          browser_lookup_override=self.BROWSER_LOOKUP)

  def test_flag_combination_duplicate(self):
    with self.assertRaises(AssertionError):
      cb.cli.BrowserConfig(
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
                  "stable": {
                      "path": "stable",
                      "flags": ["group1", "group2"]
                  }
              }
          },
          browser_lookup_override=self.BROWSER_LOOKUP)

  def test_unknown_path(self):
    with self.assertRaises(Exception):
      cb.cli.BrowserConfig(
          {"browsers": {
              "stable": {
                  "path": "path/does/not/exist",
              }
          }})
    with self.assertRaises(Exception):
      cb.cli.BrowserConfig(
          {"browsers": {
              "stable": {
                  "path": "chrome-unknown",
              }
          }})

  def test_flag_combination_simple(self):
    config = cb.cli.BrowserConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                }
            },
            "browsers": {
                "stable": {
                    "path": "stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.BROWSER_LOOKUP)
    browsers = config.variants
    self.assertEqual(len(browsers), 3)
    for browser in browsers:
      assert isinstance(browser, mockbenchmark.MockChromeStable)
      self.assertDictEqual(dict(browser.js_flags), {})
    self.assertDictEqual(dict(browsers[0].flags), {})
    self.assertDictEqual(dict(browsers[1].flags), {"--foo": None})
    self.assertDictEqual(dict(browsers[2].flags), {"--foo": "v1"})

  def test_flag_combination(self):
    config = cb.cli.BrowserConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", "v1"],
                    "--bar": [None, "", "v1"],
                }
            },
            "browsers": {
                "stable": {
                    "path": "stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3)

  def test_no_flags(self):
    config = cb.cli.BrowserConfig(
        {"browsers": {
            "stable": {
                "path": "stable",
            },
            "dev": {
                "path": "dev",
            }
        }},
        browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 2)
    browser_0 = config.variants[0]
    assert isinstance(browser_0, mockbenchmark.MockChromeStable)
    self.assertEqual(browser_0.app_path,
                     mockbenchmark.MockChromeStable.APP_PATH)
    browser_1 = config.variants[1]
    assert isinstance(browser_1, mockbenchmark.MockChromeDev)
    self.assertEqual(browser_1.app_path, mockbenchmark.MockChromeDev.APP_PATH)

  def test_inline_flags(self):
    with (mock.patch.object(
        cb.browsers.Chrome, "_extract_version", return_value="101.22.333.44"),
          mock.patch.object(
              cb.browsers.Chrome,
              "stable_path",
              new=mockbenchmark.MockChromeStable.APP_PATH)):

      config = cb.cli.BrowserConfig(
          {"browsers": {
              "stable": {
                  "path": "stable",
                  "flags": ["--foo=bar"]
              }
          }})
      self.assertEqual(len(config.variants), 1)
      browser = config.variants[0]
      # TODO: Fix once app lookup is cleaned up
      self.assertEqual(browser.app_path,
                       mockbenchmark.MockChromeStable.APP_PATH)
      self.assertEqual(browser.version, "101.22.333.44")

  def test_inline_load_safari(self):
    if not helper.platform.is_macos:
      return
    with mock.patch.object(
        cb.browsers.Safari, "_extract_version", return_value="16.0"):
      config = cb.cli.BrowserConfig(
          {"browsers": {
              "safari": {
                  "path": "safari",
              }
          }})
      self.assertEqual(len(config.variants), 1)

  def test_flag_combination_with_fixed(self):
    config = cb.cli.BrowserConfig(
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
                "stable": {
                    "path": "stable",
                    "flags": ["group1"]
                }
            }
        },
        browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3)
    for browser in config.variants:
      assert isinstance(browser, mockbenchmark.MockChromeStable)
      self.assertEqual(browser.app_path,
                       mockbenchmark.MockChromeStable.APP_PATH)

  def test_flag_group_combination(self):
    config = cb.cli.BrowserConfig(
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
                "stable": {
                    "path": "stable",
                    "flags": ["group1", "group2", "group3"]
                }
            }
        },
        browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3 * 2)


class TestFlagGroupConfig(unittest.TestCase):

  def parse(self, config_dict):
    config = cb.cli.FlagGroupConfig("test", config_dict)
    variants = list(config.get_variant_items())
    return variants

  def test_empty(self):
    config = cb.cli.FlagGroupConfig("empty_name", dict())
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
