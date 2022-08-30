# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import json
import unittest
from pathlib import Path
import unittest.mock as mock

from typing import Optional, Dict

import pyfakefs.fake_filesystem_unittest
import crossbench

import crossbench.flags
from crossbench.cli import BrowserConfig, CrossBenchCLI, FlagGroupConfig
from crossbench import browsers, helper


class SysExitException(Exception):

  def __init__(self):
    super().__init__('sys.exit')


class TestCLI(pyfakefs.fake_filesystem_unittest.TestCase):

  def setUp(self):
    self.setUpPyfakefs()

  def run_cli(self, *args, raises=None):
    with mock.patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
      cli = CrossBenchCLI()
      if raises:
        with self.assertRaises(raises):
          cli.run(args)
      else:
        cli.run(args)
      return mock_stdout.getvalue()

  def test_describe(self):
    stdout = self.run_cli("describe")
    data = json.loads(stdout)
    self.assertIn("benchmarks", data)
    self.assertIn("probes", data)
    self.assertIsInstance(data['benchmarks'], dict)
    self.assertIsInstance(data['probes'], dict)

  def test_help(self):
    with mock.patch('sys.exit', side_effect=SysExitException) as exit_mock:
      stdout = self.run_cli('--help', raises=SysExitException)
      self.assertTrue(exit_mock.called)
      exit_mock.assert_called_with(0)
      self.assertGreater(len(stdout), 0)

  def test_help_subcommand(self):
    for benchmark in CrossBenchCLI.BENCHMARKS:
      with mock.patch('sys.exit', side_effect=SysExitException()) as exit_mock:
        stdout = self.run_cli(benchmark.NAME, '--help', raises=SysExitException)
        self.assertTrue(exit_mock.called)
        exit_mock.assert_called_with(0)
        self.assertGreater(len(stdout), 0)


FlagsInitialDataType = crossbench.flags.Flags.InitialDataType


class MockBrowser(browsers.Browser):
  BIN_PATH = None

  def __init__(self,
               label: str,
               path: Path,
               flags: FlagsInitialDataType = None,
               cache_dir: Optional[Path] = None):
    path = Path(self.BIN_PATH)
    super().__init__(label, path, flags, cache_dir, type="test")

  def _extract_version(self):
    return "100.22.33.44"


class MockBrowserStable(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = Path("/Applications/Chrome.app")
  else:
    BIN_PATH = Path("/usr/bin/chrome")


class MockBrowserDev(MockBrowser):
  if helper.platform.is_macos:
    BIN_PATH = Path("/Applications/ChromeDev.app")
  else:
    BIN_PATH = Path("/usr/bin/chrome")


class TestBrowserConfig(pyfakefs.fake_filesystem_unittest.TestCase):
  EXAMPLE_CONFIG_PATH = Path(
      __file__).parent.parent / 'browser.config.example.hjson'

  BROWSER_LOOKUP = {
      "stable": MockBrowserStable,
      "dev": MockBrowserDev,
      "chrome-stable": MockBrowserStable,
      "chrome-dev": MockBrowserDev,
  }

  def setUp(self):
    # TODO: Move to separate common helper class
    self.setUpPyfakefs(modules_to_reload=[crossbench])
    if helper.platform.is_macos:
      self.fs.create_file(MockBrowserStable.BIN_PATH / "Contents" / "MacOS" /
                          "Chrome")
      self.fs.create_file(MockBrowserDev.BIN_PATH / "Contents" / "MacOS" /
                          "Chrome")
    else:
      self.fs.create_file(MockBrowserStable.BIN_PATH)
      self.fs.create_file(MockBrowserDev.BIN_PATH)

  def test_load_browser_config_template(self):
    if not self.EXAMPLE_CONFIG_PATH.exists():
      return
    self.fs.add_real_file(self.EXAMPLE_CONFIG_PATH)
    with self.EXAMPLE_CONFIG_PATH.open() as f:
      config = BrowserConfig.load(f, lookup=self.BROWSER_LOOKUP)
    self.assertIn('default', config.flag_groups)
    self.assertGreaterEqual(len(config.flag_groups), 1)
    self.assertGreaterEqual(len(config.variants), 1)

  def test_flag_combination_duplicate(self):
    with self.assertRaises(AssertionError):
      BrowserConfig(
          {
              "flags": {
                  "group1": {
                      "--foo": [None, "", 'v1'],
                  },
                  "group2": {
                      "--foo": [None, "", 'v1'],
                  }
              },
              "browsers": {
                  "stable": {
                      "path": "stable",
                      "flags": ["group1", "group2"]
                  }
              }
          },
          lookup=self.BROWSER_LOOKUP)

  def test_flag_combination(self):
    config = BrowserConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", 'v1'],
                    "--bar": [None, "", 'v1'],
                }
            },
            "browsers": {
                "stable": {
                    "path": "stable",
                    "flags": ["group1"]
                }
            }
        },
        lookup=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3)

  def test_flag_combination_with_fixed(self):
    config = BrowserConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", 'v1'],
                    "--bar": [None, "", 'v1'],
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
        lookup=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3)

  def test_flag_group_combination(self):
    config = BrowserConfig(
        {
            "flags": {
                "group1": {
                    "--foo": [None, "", 'v1'],
                },
                "group2": {
                    "--bar": [None, "", 'v1'],
                },
                "group3": {
                    "--other": ["v1", 'v2'],
                }
            },
            "browsers": {
                "stable": {
                    "path": "stable",
                    "flags": ["group1", "group2", "group3"]
                }
            }
        },
        lookup=self.BROWSER_LOOKUP)
    self.assertEqual(len(config.variants), 3 * 3 * 2)


class TestFlagGroupConfig(unittest.TestCase):

  def parse(self, config_dict):
    config = FlagGroupConfig("test", config_dict)
    variants = list(config.get_variant_items())
    return variants

  def test_empty(self):
    config = FlagGroupConfig('empty_name', dict())
    self.assertEqual(config.name, 'empty_name')
    variants = list(config.get_variant_items())
    self.assertEqual(len(variants), 0)

  def test_single_flag(self):
    variants = self.parse({'--foo': set()})
    self.assertListEqual(variants, [
        (),
    ])

    variants = self.parse({'--foo': []})
    self.assertListEqual(variants, [
        (),
    ])

    variants = self.parse({'--foo': (None,)})
    self.assertListEqual(variants, [
        (None,),
    ])

    variants = self.parse({'--foo': ("",)})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(
        variants[0],
        (('--foo', None),),
    )

    variants = self.parse({'--foo': (
        "",
        None,
    )})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(variants[0], (('--foo', None), None))

    variants = self.parse({'--foo': (
        "v1",
        "v2",
        "",
        None,
    )})
    self.assertEqual(len(variants), 1)
    self.assertTupleEqual(variants[0], (('--foo', "v1"), ('--foo', "v2"),
                                        ('--foo', None), None))

  def test_two_flags(self):
    variants = self.parse({'--foo': [], '--bar': []})
    self.assertListEqual(variants, [(), ()])

    variants = self.parse({'--foo': "a", '--bar': "b"})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (("--foo", "a"),))
    self.assertTupleEqual(variants[1], (("--bar", "b"),))

    variants = self.parse({'--foo': ["a1", "a2"], '--bar': "b"})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (
        ("--foo", "a1"),
        ("--foo", "a2"),
    ))
    self.assertTupleEqual(variants[1], (("--bar", "b"),))

    variants = self.parse({'--foo': ["a1", "a2"], '--bar': ["b1", "b2"]})
    self.assertEqual(len(variants), 2)
    self.assertTupleEqual(variants[0], (
        ("--foo", "a1"),
        ("--foo", "a2"),
    ))
    self.assertTupleEqual(variants[1], (
        ("--bar", "b1"),
        ("--bar", "b2"),
    ))
