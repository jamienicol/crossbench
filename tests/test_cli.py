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
from crossbench.cli import BrowserConfig, CrossBenchCLI, FlagGroupConfig

from . import mockbenchmark


class SysExitException(Exception):

  def __init__(self):
    super().__init__("sys.exit")


class TestCLI(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    self.setUpPyfakefs()

  def run_cli(self, *args, raises=None):
    with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
      cli = CrossBenchCLI()
      if raises:
        with self.assertRaises(raises):
          cli.run(args)
      else:
        cli.run(args)
      return mock_stdout.getvalue()

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
    for benchmark in CrossBenchCLI.BENCHMARKS:
      with mock.patch("sys.exit", side_effect=SysExitException()) as exit_mock:
        stdout = self.run_cli(benchmark.NAME, "--help", raises=SysExitException)
        self.assertTrue(exit_mock.called)
        exit_mock.assert_called_with(0)
        self.assertGreater(len(stdout), 0)


class TestBrowserConfig(pyfakefs.fake_filesystem_unittest.TestCase):
  EXAMPLE_CONFIG_PATH = pathlib.Path(
      __file__).parent.parent / "browser.config.example.hjson"


  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])
    mockbenchmark.MockBrowserStable.setup_fs(self.fs)
    mockbenchmark.MockBrowserDev.setup_fs(self.fs)
    self.BROWSER_LOOKUP = {
        "stable": (mockbenchmark.MockBrowserStable,
                   mockbenchmark.MockBrowserStable.BIN_PATH),
        "dev": (mockbenchmark.MockBrowserDev,
                mockbenchmark.MockBrowserDev.BIN_PATH),
        "chrome-stable": (mockbenchmark.MockBrowserStable,
                          mockbenchmark.MockBrowserStable.BIN_PATH),
        "chrome-dev": (mockbenchmark.MockBrowserDev,
                       mockbenchmark.MockBrowserDev.BIN_PATH),
    }

  def test_load_browser_config_template(self):
    if not self.EXAMPLE_CONFIG_PATH.exists():
      return
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open() as f:
      config = BrowserConfig.load(
          f, browser_lookup_override=self.BROWSER_LOOKUP)
    self.assertIn("default", config.flag_groups)
    self.assertGreaterEqual(len(config.flag_groups), 1)
    self.assertGreaterEqual(len(config.variants), 1)

  def test_flag_combination_duplicate(self):
    with self.assertRaises(AssertionError):
      BrowserConfig(
          {
              "flags": {
                  "group1": {
                      "--foo": [None, "", "v1"],
                  },
                  "group2": {
                      "--foo": [None, "", "v1"],
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

  def test_flag_combination(self):
    config = BrowserConfig(
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

  def test_flag_combination_with_fixed(self):
    config = BrowserConfig(
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

  def test_flag_group_combination(self):
    config = BrowserConfig(
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
    config = FlagGroupConfig("test", config_dict)
    variants = list(config.get_variant_items())
    return variants

  def test_empty(self):
    config = FlagGroupConfig("empty_name", dict())
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
