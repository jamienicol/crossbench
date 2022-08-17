#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import itertools
import json
import logging
from pathlib import Path
from typing import Iterable, Optional, Type

import hjson
import crossbench
from crossbench import benchmarks, browsers, helper, probes, runner, flags


class FlagGroupConfig:
  """
  This object is create from configuration files and mainly contains a mapping
  from flag-names to multiple values.
  """
  def __init__(self, name: str, variants: dict):
    self.name = name
    self._variants: dict[str, Iterable[str]] = {}
    for flag_name, flag_variants_or_value in variants.items():
      assert flag_name not in self._variants
      assert len(flag_name) > 0
      if isinstance(flag_variants_or_value, set):
        self._variants[flag_name] = flag_variants_or_value
      else:
        assert isinstance(flag_variants_or_value, str)
        self._variants[flag_name] = (flag_variants_or_value, )

  def get_variant_items(self) -> Iterable[Optional[tuple[str, str]]]:
    variants = []
    for flag_name, flag_values in self._variants.items():
      flag_variants = tuple(
          self._map(flag_name, flag_value) for flag_value in flag_values)
      variants.append(flag_variants)
    return variants

  @staticmethod
  def _map(flag_name : str, flag_value : Optional[str]):
    if flag_value is None:
      return None
    if flag_value == "":
      return (flag_name, None)
    return (flag_name, flag_value)


class Config:
  def __init__(self, path=None):
    self._flag_groups : dict[str, FlagGroupConfig] = {}
    self.browsers : list[browsers.Browser] = []
    if path:
      with path.open() as f:
        try:
          config = hjson.load(f)
        except hjson.decoder.HjsonDecodeError as e:
          raise Exception(f"Failed to parse config file: {path}") from e
      for group_name, group_config in config['flags'].items():
        self._parse_flag_group(group_name, group_config)
      for group_name, group_config in config['browsers'].items():
        self.browsers += self._parse_browser(group_name, group_config)

  def _parse_flag_group(self, name, data):
    assert name not in self._flag_groups, (
        f"flag-group='{name}' exists already")
    variants = {}
    for flag_name, values in data.items():
      if not flag_name.startswith("-"):
        raise Exception(f"Invalid flag name: '{flag_name}'")
      if flag_name not in variants:
        flag_values = variants[flag_name] = set()
      else:
        flag_values = variants[flag_name]
      if isinstance(values, str):
        values = [values]
      for value in values:
        assert value not in flag_values, (
            "Same flag variant was specified more than once: "
            f"'{value}' for entry '{flag_name}")
        flag_values.add(value)
    self._flag_groups[name] = FlagGroupConfig(name, variants)

  def _parse_browser(self, name, data):
    path = self._get_browser_path(data['path'])
    assert path.exists(), f"Browser='{name}' path='{path}' does not exist."
    cls = self._get_browser_cls_from_path(path)
    variants_flags = tuple(
        cls.DEFAULT_FLAGS(flags) for flags in self._parse_flags(name, data))
    logging.info(
        f"Running browser '{name}' with {len(variants_flags)} flag variants:")
    for i in range(len(variants_flags)):
      logging.info("   %s: %s", i, variants_flags[i])
    return [
        cls(label=self._flags_to_label(name, flags), path=path, flags=flags)
        for flags in variants_flags
    ]

  def _flags_to_label(self, name, flags):
    return f"{name}_{browsers.convert_flags_to_label(*flags.get_list())}"

  def _parse_flags(self, name, data):
    flags_product = []
    flag_group_names = data['flags']
    assert isinstance(flag_group_names, list), \
        f"'flags' is not a list for browser='{name}'"
    for flag_group_name in flag_group_names:
      # Use temporary FlagGroupConfig for inline fixed flag definition
      if flag_group_name.startswith('--'):
        flag_name, flag_value = flags.Flags.split(flag_group_name)
        flag_group = FlagGroupConfig("temporary", {flag_name: flag_value})
        assert flag_group_name not in self._flag_groups
      else:
        flag_group = self._flag_groups.get(flag_group_name, None)
        assert flag_group is not None, (f"Flag-group='{flag_group_name}' "
                                        f"for browser='{name}' does not exist.")
      flags_product += flag_group.get_variant_items()
    if len(flags_product) == 0:
      # use empty default
      return (dict(), )
    flags_product = itertools.product(*flags_product)
    # Filter out (.., None) value
    flags_product = list(
        list(flag_item for flag_item in flags_items if flag_item is not None)
        for flags_items in flags_product)
    assert len(flags_product) > 0
    return flags_product

  def _get_browser_cls_from_path(self, path) -> Type[browsers.Browser]:
    cls = browsers.ChromeWebDriver
    if 'Safari' in str(path):
      return browsers.SafariWebDriver
    else:
      assert 'chrome' in str(path).lower(), f"Unsupported browser='{path}'"
    return cls

  def load_from_args(self, args):
    path = self._get_browser_path(args.browser or 'chrome')
    logging.warning("SELECTED BROWSER: %s", path)
    cls = self._get_browser_cls_from_path(path)
    flags = cls.default_flags()
    if args.enable_features:
      for feature in args.enabled_features.split(','):
        flags.features.enable(feature)
    if args.disable_features:
      for feature in args.disabled_features.split(','):
        flags.features.disable(feature)
    if args.js_flags:
      flags.js_flags.update(args.js_flags.split(','))
    for flag_str in args.other_browser_args:
      flags.set(*crossbench.flags.Flags.split(flag_str))

    label = browsers.convert_flags_to_label(*flags.get_list())
    browser = cls(label=label, path=path, flags=flags)
    self.browsers.append(browser)

  def _get_browser_path(self, path_or_short_name: str) -> Path:
    short_name = path_or_short_name.lower()
    if short_name == 'chrome' or short_name == 'stable':
      return browsers.Chrome.stable_path
    if short_name == 'chrome dev' or short_name == 'dev':
      return browsers.Chrome.dev_path
    if short_name == 'chrome canary' or short_name == 'canary':
      return browsers.Chrome.canary_path
    if short_name == 'safari':
      return browsers.Safari.default_path
    if short_name == 'safari technology preview' or short_name == 'tp':
      return browsers.Safari.technology_preview_path
    path = Path(path_or_short_name)
    if path.exists():
      return path
    path = path.expanduser()
    if path.exists():
      return path
    if len(path.parts) > 1:
      raise Exception(f"Browser at '{path}' does not exist.")
    raise Exception(
        f"Unknown browser path or short name: '{path_or_short_name}'")


class BenchmarkCli:

  BENCHMARKS = (
      benchmarks.Speedometer20Runner,
      benchmarks.JetStream2Runner,
      benchmarks.MotionMark12Runner,
      benchmarks.PageLoadRunner,
  )

  GENERAL_PURPOSE_PROBES_BY_NAME = {
      cls.NAME: cls
      for cls in probes.GENERAL_PURPOSE_PROBES
  }

  def __init__(self):
    self.parser = argparse.ArgumentParser()
    self._setup_parser()
    self._setup_subparser()

  def _setup_parser(self):
    self.parser.add_argument("-v",
                             "--verbose",
                             dest="verbosity",
                             action="count",
                             default=0,
                             help="Increase output verbosity (0..2)")

  def _setup_subparser(self):
    self.subparsers = self.parser.add_subparsers(title='Subcommands',
                                                 dest="subcommand",
                                                 required=True)
    for benchmark_cls in self.BENCHMARKS:
      self._setup_benchmark_subparser(benchmark_cls)
    describe_parser = self.subparsers.add_parser(
        "describe", help="Print all benchmarks and stories")
    describe_parser.set_defaults(subcommand=self.describe_subcommand)

  def describe_subcommand(self, args):
    data = {
        "benchmarks": {
            benchmark_cls.NAME: benchmark_cls.describe()
            for benchmark_cls in self.BENCHMARKS
        },
        "probes": {
            probe_cls.NAME: probe_cls.__doc__.strip()
            for probe_cls in probes.GENERAL_PURPOSE_PROBES
        }
    }
    print(json.dumps(data, indent=2))

  def _setup_benchmark_subparser(self, benchmark_cls):
    subparser = benchmark_cls.add_cli_parser(self.subparsers)
    assert isinstance(subparser, argparse.ArgumentParser), (
        f"Benchmark class {benchmark_cls}.add_cli_parser did not return "
        f"an ArgumentParser: {subparser}")
    subparser.add_argument("--dry-run",
                           action="store_true",
                           default=False,
                           help="Don't run any browsers or probes")
    browser_group = subparser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--browser",
        help="Browser binary. Use this to test a single browser. "
        "Use a shortname [chrome, stable, dev, canary, safari] "
        "for system default browsers or a full path")
    browser_group.add_argument(
        "--browser-config",
        type=Path,
        help="Browser configuration.json file. "
        "Use this to run multiple browsers and/or multiple flag configurations."
    )
    subparser.add_argument(
        "--probe",
        action='append',
        default=[],
        choices=self.GENERAL_PURPOSE_PROBES_BY_NAME.keys(),
        help=(
            "Enable general purpose probes to measure data on all stories. "
            "This argument can be specified multiple times to add more probes"))
    subparser.add_argument('other_browser_args', nargs="*")
    chrome_args = subparser.add_argument_group(
        "Chrome-forwarded Options",
        "For convenience these arguments are directly are forwarded "
        "directly to chrome. Any other browser option can be passed "
        "after the '--' arguments separator.")
    chrome_args.add_argument("--js-flags", dest="js_flags")

    DOC = "See chrome's base/feature_list.h source file for more details"
    chrome_args.add_argument(
        "--enable-features",
        help="Comma-separated list of enabled chrome features. " + DOC,
        default='')
    chrome_args.add_argument(
        "--disable-features",
        help="Command-separated list of disabled chrome features. " + DOC,
        default='')
    subparser.set_defaults(subcommand=self.benchmark_subcommand,
                           benchmark_cls=benchmark_cls)

  def benchmark_subcommand(self, args):
    if args.browser_config:
      path = args.browser_config.expanduser()
      if not path.exists():
        raise argparse.ArgumentTypeError(
            f"Given path '{path.absolute}' does not exist")
      assert args.browser is None, (
          "Cannot specify --browser and --browser-config at the same time")
      args.browser_config = Config(path)
    else:
      args.browser_config = Config()
      args.browser_config.load_from_args(args)
    args.browsers = args.browser_config.browsers
    benchmark_cls = args.benchmark_cls
    assert issubclass(benchmark_cls, runner.Runner), \
        f"benchmark_cls={benchmark_cls} is not subclass of Runner"
    kwargs = benchmark_cls.kwargs_from_cli(args)
    benchmark = benchmark_cls(**kwargs)
    for probe_name in args.probe:
      probe = self.GENERAL_PURPOSE_PROBES_BY_NAME[probe_name]()
      benchmark.attach_probe(probe, matching_browser_only=True)
    benchmark.run(is_dry_run=args.dry_run)
    print(f"RESULTS: {benchmark.out_dir / 'results.json' }")

  def run(self):
    args = self.parser.parse_args()
    self._initialize_logging(args)
    args.subcommand(args)

  def _initialize_logging(self, args):
    logging.getLogger().setLevel(logging.INFO)
    consoleHandler = logging.StreamHandler()
    if args.verbosity == 0:
      consoleHandler.setLevel(logging.WARNING)
    elif args.verbosity == 1:
      consoleHandler.setLevel(logging.INFO)
    elif args.verbosity > 1:
      consoleHandler.setLevel(logging.DEBUG)
      logging.getLogger().setLevel(logging.DEBUG)
    consoleHandler.addFilter(logging.Filter("root"))
    logging.getLogger().addHandler(consoleHandler)


if __name__ == "__main__":
  cli = BenchmarkCli()
  cli.run()
