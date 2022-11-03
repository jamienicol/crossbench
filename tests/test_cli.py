# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import json
import pathlib
import unittest
import unittest.mock as mock

import pyfakefs.fake_filesystem_unittest

import crossbench as cb
from crossbench import helper
import crossbench.probes.all
from crossbench import cli

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
      return mock_stdout.getvalue()

  def test_invalid(self):
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      self.run_cli(
          "unknown subcommand", "--invalid flag", raises=SysExitException)

  def test_describe(self):
    stdout = self.run_cli("describe", "--json")
    data = json.loads(stdout)
    self.assertIn("benchmarks", data)
    self.assertIn("probes", data)
    self.assertIsInstance(data["benchmarks"], dict)
    self.assertIsInstance(data["probes"], dict)

  def test_help(self):
    with mock.patch("sys.exit", side_effect=SysExitException) as exit_mock:
      stdout = self.run_cli("--help", raises=SysExitException)
      self.assertTrue(exit_mock.called)
      exit_mock.assert_called_with(0)
      self.assertGreater(len(stdout), 0)

  def test_help_subcommand(self):
    for benchmark in cli.CrossBenchCLI.BENCHMARKS:
      with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
        stdout = self.run_cli(benchmark.NAME, "--help", raises=SysExitException)
        self.assertTrue(exit_mock.called)
        exit_mock.assert_called_with(0)
        self.assertGreater(len(stdout), 0)

  def test_invalid_probe(self):
    with (self.assertRaises(ValueError),
          mock.patch.object(
              cli.CrossBenchCLI, "_get_browsers",
              return_value=self.browsers)):
      self.run_cli("loading", "--probe=invalid_probe_name")

  def test_basic_probe_setting(self):
    with mock.patch.object(
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
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
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
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
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
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
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
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
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe-config={config_file}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)

  def test_probe_invalid_inline_json_config(self):
    with (self.assertRaises(ValueError),
          mock.patch.object(
              cli.CrossBenchCLI, "_get_browsers",
              return_value=self.browsers)):
      self.run_cli("loading", "--probe=v8.log{invalid json: d a t a}",
                   f"--urls=cnn", "--skip-checklist")

  def test_probe_empty_inline_json_config(self):
    js_flags = ["--log-foo", "--log-bar"]
    with mock.patch.object(
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
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
        cli.CrossBenchCLI, "_get_browsers", return_value=self.browsers):
      url = "http://test.com"
      self.run_cli("loading", f"--probe=v8.log{json_config}", f"--urls={url}",
                   "--skip-checklist")
      for browser in self.browsers:
        self.assertListEqual([url], browser.url_list)
        for flag in js_flags:
          self.assertIn(flag, browser.js_flags)


class TestProbeConfig(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])

  def parse_config(self, config_data) -> cli.ProbeConfig:
    probe_config_file = pathlib.Path("/probe.config.hjson")
    with probe_config_file.open("w") as f:
      json.dump(config_data, f)
    with probe_config_file.open() as f:
      return cli.ProbeConfig.load(f)

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

class TestBrowserConfig(pyfakefs.fake_filesystem_unittest.TestCase):
  EXAMPLE_CONFIG_PATH = pathlib.Path(
      __file__).parent.parent / "browser.config.example.hjson"


  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])
    mockbenchmark.MockChromeStable.setup_fs(self.fs)
    mockbenchmark.MockChromeDev.setup_fs(self.fs)
    mockbenchmark.MockChromeCanary.setup_fs(self.fs)
    if helper.platform.is_macos:
      mockbenchmark.MockSafari.setup_fs(self.fs)
    self.BROWSER_LOOKUP = {
        "stable": (mockbenchmark.MockChromeStable,
                   mockbenchmark.MockChromeStable.BIN_PATH),
        "dev":
            (mockbenchmark.MockChromeDev, mockbenchmark.MockChromeDev.BIN_PATH),
        "chrome-stable": (mockbenchmark.MockChromeStable,
                          mockbenchmark.MockChromeStable.BIN_PATH),
        "chrome-dev":
            (mockbenchmark.MockChromeDev, mockbenchmark.MockChromeDev.BIN_PATH),
    }

  def test_load_browser_config_template(self):
    if not self.EXAMPLE_CONFIG_PATH.exists():
      return
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open() as f:
      config = cli.BrowserConfig.load(
          f, browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertIn("default", config.flag_groups)
    self.assertGreaterEqual(len(config.flag_groups), 1)
    self.assertGreaterEqual(len(config.variants), 1)

  def test_flag_combination_invalid(self):
    with self.assertRaises(Exception):
      cli.BrowserConfig(
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
      cli.BrowserConfig(
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
      cli.BrowserConfig({"browsers": {"stable": {"path": "path/does/not/exist",}}})
    with self.assertRaises(Exception):
      cli.BrowserConfig({"browsers": {"stable": {"path": "chrome-unknown",}}})

  def test_flag_combination_simple(self):
    config = cli.BrowserConfig(
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
    config = cli.BrowserConfig(
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
    config = cli.BrowserConfig(
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
    self.assertEqual(config.variants[0].path,
                     mockbenchmark.MockChromeStable.BIN_PATH)
    self.assertEqual(config.variants[1].path,
                     mockbenchmark.MockChromeDev.BIN_PATH)

  def test_inline_flags(self):
    with (mock.patch.object(
        cb.browsers.Chrome, "_extract_version", return_value="101.22.333.44"),
          mock.patch.object(
              cb.browsers.Chrome,
              "stable_path",
              new=mockbenchmark.MockChromeStable.BIN_PATH)):

      config = cli.BrowserConfig(
          {"browsers": {
              "stable": {
                  "path": "stable",
                  "flags": ["--foo=bar"]
              }
          }})
      self.assertEqual(len(config.variants), 1)
      browser = config.variants[0]
      self.assertEqual(browser.path, mockbenchmark.MockChromeStable.BIN_PATH)
      self.assertEqual(browser.version, "101.22.333.44")

  def test_inline_load_safari(self):
    if not helper.platform.is_macos:
      return
    with mock.patch.object(
        cb.browsers.Safari, "_extract_version", return_value="16.0"):
      config = cli.BrowserConfig({"browsers": {"safari": {"path": "safari",}}})
      self.assertEqual(len(config.variants), 1)

  def test_flag_combination_with_fixed(self):
    config = cli.BrowserConfig(
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
      self.assertEqual(browser.path, mockbenchmark.MockChromeStable.BIN_PATH)

  def test_flag_group_combination(self):
    config = cli.BrowserConfig(
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
    config = cli.FlagGroupConfig("test", config_dict)
    variants = list(config.get_variant_items())
    return variants

  def test_empty(self):
    config = cli.FlagGroupConfig("empty_name", dict())
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
