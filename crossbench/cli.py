# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import itertools
import json
import logging
import pathlib
from tabulate import tabulate
from typing import Dict, Iterable, List, Optional, Tuple, Type, Union

import crossbench as cb

try:
  import hjson
except ModuleNotFoundError:
  logging.debug("hjson module not found")
  hjson = None


class FlagGroupConfig:
  """
  This object is create from configuration files and mainly contains a mapping
  from flag-names to multiple values.
  """

  _variants: Dict[str, Iterable[Optional[str]]]
  name: str

  def __init__(self, name: str,
               variants: Dict[str, Union[Iterable[Optional[str]], str]]):
    self.name = name
    self._variants = {}
    for flag_name, flag_variants_or_value in variants.items():
      assert flag_name not in self._variants
      assert flag_name
      if isinstance(flag_variants_or_value, str):
        self._variants[flag_name] = (str(flag_variants_or_value),)
      else:
        assert isinstance(flag_variants_or_value, Iterable)
        flag_variants = tuple(flag_variants_or_value)
        assert len(flag_variants) == len(set(flag_variants)), (
            "Flag variant contains duplicate entries: {flag_variants}")
        self._variants[flag_name] = tuple(flag_variants_or_value)

  def get_variant_items(self) -> Iterable[Optional[Tuple[str, Optional[str]]]]:
    for flag_name, flag_values in self._variants.items():
      yield tuple(
          self._map(flag_name, flag_value) for flag_value in flag_values)

  @staticmethod
  def _map(flag_name: str, flag_value: Optional[str]):
    if flag_value is None:
      return None
    if flag_value == "":
      return (flag_name, None)
    return (flag_name, flag_value)


class BrowserConfig:

  @classmethod
  def load(cls, f, browser_lookup_override={}):
    try:
      if hjson:
        config = hjson.load(f)
      else:
        config = json.load(f)
    except ValueError as e:
      raise ValueError(f"Failed to parse config file: {f}") from e
    return cls(config, browser_lookup_override)

  flag_groups: Dict[str, FlagGroupConfig]
  variants: List[cb.browsers.Browser]

  def __init__(self,
               raw_config_data: Optional[Dict] = None,
               browser_lookup_override: Dict[
                   str, Tuple[Type[cb.browsers.Browser], pathlib.Path]] = {}):
    self.flag_groups = {}
    self.variants = []
    self._browser_lookup_override = browser_lookup_override
    if raw_config_data:
      if "flags" in raw_config_data:
        for flag_name, group_config in raw_config_data["flags"].items():
          self._parse_flag_group(flag_name, group_config)
      assert "browsers" in raw_config_data, (
          "Config does not provide a 'browsers' dict.")
      assert len(raw_config_data["browsers"]), ("Config contains empty 'browsers' dict.")
      for name, browser_config in raw_config_data["browsers"].items():
        self._parse_browser(name, browser_config)

  def _parse_flag_group(self, name, raw_flag_group_data):
    assert name not in self.flag_groups, (f"flag-group='{name}' exists already")
    variants = {}
    for flag_name, values in raw_flag_group_data.items():
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
            f"'{value}' for entry '{flag_name}'")
        flag_values.add(value)
    self.flag_groups[name] = FlagGroupConfig(name, variants)

  def _parse_browser(self, name, raw_browser_data):
    path_or_identifier = raw_browser_data["path"]
    if path_or_identifier in self._browser_lookup_override:
      cls, path = self._browser_lookup_override[path_or_identifier]
    else:
      path = self._get_browser_path(path_or_identifier)
      cls = self._get_browser_cls_from_path(path)
    assert path.exists(), f"Browser='{name}' path='{path}' does not exist."
    variants_flags = tuple(
        cls.default_flags(flags)
        for flags in self._parse_flags(name, raw_browser_data))
    logging.info("Running browser '%s' with %s flag variants:", name,
                 len(variants_flags))
    for i in range(len(variants_flags)):
      logging.info("   %s: %s", i, variants_flags[i])
    # pytype: disable=not-instantiable
    self.variants += [
        cls(label=self._flags_to_label(name, flags), path=path, flags=flags)
        for flags in variants_flags
    ]
    # pytype: enable=not-instantiable

  def _flags_to_label(self, name: str, flags: cb.flags.Flags) -> str:
    return f"{name}_{cb.browsers.convert_flags_to_label(*flags.get_list())}"

  def _parse_flags(self, name, data):
    flags_product = []
    flag_group_names = data["flags"]
    assert isinstance(flag_group_names,
                      list), (f"'flags' is not a list for browser='{name}'")
    for flag_group_name in flag_group_names:
      # Use temporary FlagGroupConfig for inline fixed flag definition
      if flag_group_name.startswith("--"):
        flag_name, flag_value = cb.flags.Flags.split(flag_group_name)
        flag_group = FlagGroupConfig("temporary", {flag_name: flag_value})
        assert flag_group_name not in self.flag_groups
      else:
        flag_group = self.flag_groups.get(flag_group_name, None)
        assert flag_group is not None, (f"Flag-group='{flag_group_name}' "
                                        f"for browser='{name}' does not exist.")
      flags_product += flag_group.get_variant_items()
    if len(flags_product) == 0:
      # use empty default
      return (dict(),)
    flags_product = itertools.product(*flags_product)
    # Filter out (.., None) value
    flags_product = list(
        list(flag_item
             for flag_item in flags_items
             if flag_item is not None)
        for flags_items in flags_product)
    assert flags_product
    return flags_product

  def _get_browser_cls_from_path(self, path):
    path_str = str(path).lower()
    if "safari" in path_str:
      return cb.browsers.SafariWebDriver
    if "chrome" in path_str:
      return cb.browsers.ChromeWebDriver
    raise Exception(f"Unsupported browser='{path}'")

  def load_from_args(self, args):
    path = self._get_browser_path(args.browser or "chrome")
    logging.warning("SELECTED BROWSER: %s", path)
    cls = self._get_browser_cls_from_path(path)
    flags = cls.default_flags()
    if args.enable_features:
      for feature in args.enabled_features.split(","):
        flags.features.enable(feature)
    if args.disable_features:
      for feature in args.disabled_features.split(","):
        flags.features.disable(feature)
    if args.js_flags:
      flags.js_flags.update(args.js_flags.split(","))
    for flag_str in args.other_browser_args:
      flags.set(*cb.flags.Flags.split(flag_str))

    label = cb.browsers.convert_flags_to_label(*flags.get_list())
    browser = cls(label=label, path=path, flags=flags)
    self.variants.append(browser)

  def _get_browser_path(self, path_or_identifier: str) -> pathlib.Path:
    identifier = path_or_identifier.lower()
    # We're not using a dict-based lookup here, since not all browsers are
    # available on all platforms
    if identifier == "chrome" or identifier == "stable":
      return cb.browsers.Chrome.stable_path
    if identifier == "chrome dev" or identifier == "dev":
      return cb.browsers.Chrome.dev_path
    if identifier == "chrome canary" or identifier == "canary":
      return cb.browsers.Chrome.canary_path
    if identifier == "safari":
      return cb.browsers.Safari.default_path
    if identifier == "safari technology preview" or identifier == "tp":
      return cb.browsers.Safari.technology_preview_path
    path = pathlib.Path(path_or_identifier)
    if path.exists():
      return path
    path = path.expanduser()
    if path.exists():
      return path
    if len(path.parts) > 1:
      raise Exception(f"Browser at '{path}' does not exist.")
    raise Exception(
        f"Unknown browser path or short name: '{path_or_identifier}'")


class CrossBenchCLI:

  BENCHMARKS = (
      cb.benchmarks.Speedometer20Runner,
      cb.benchmarks.JetStream2Benchmark,
      cb.benchmarks.MotionMark12Benchmark,
      cb.benchmarks.PageLoadBenchmark,
  )

  GENERAL_PURPOSE_PROBES_BY_NAME = {
      cls.NAME: cls for cls in cb.probes.GENERAL_PURPOSE_PROBES
  }

  RUNNER_CLS =  cb.runner.Runner

  def __init__(self):
    self.parser = argparse.ArgumentParser()
    self._setup_parser()
    self._setup_subparser()

  def _setup_parser(self):
    self.parser.add_argument(
        "-v",
        "--verbose",
        dest="verbosity",
        action="count",
        default=0,
        help="Increase output verbosity (0..2)")

  def _setup_subparser(self):
    self.subparsers = self.parser.add_subparsers(
        title="Subcommands", dest="subcommand", required=True)

    for benchmark_cls in self.BENCHMARKS:
      self._setup_benchmark_subparser(benchmark_cls)

    describe_parser = self.subparsers.add_parser(
        "describe", aliases=["desc"], help="Print all benchmarks and stories")
    describe_parser.add_argument(
        "filter",
        nargs="?",
        choices=["all", "benchmarks", "probes"],
        default="all",
        help="Limit output to the given category, defaults to 'all'")
    describe_parser.add_argument("--json",
                                 default=False,
                                 action="store_true",
                                 help="Print the data as json data")
    describe_parser.set_defaults(subcommand=self.describe_subcommand)

  def describe_subcommand(self, args):
    data = {
        "benchmarks": {
            benchmark_cls.NAME: benchmark_cls.describe()
            for benchmark_cls in self.BENCHMARKS
        },
        "probes": {
            probe_cls.NAME: probe_cls.__doc__.strip()
            for probe_cls in cb.probes.GENERAL_PURPOSE_PROBES
        }
    }
    if args.json:
      if args.filter == "probes":
        data = data["probes"]
      elif args.filter == "benchmarks":
        data = data["benchmarks"]
      else:
        assert args.filter == "all"
      print(json.dumps(data, indent=2))
      return
    # Create tabular format
    if args.filter == "all" or args.filter == "benchmarks":
      table = [["Benchmark", "Property", "Value"]]
      for benchmark_name, values in data['benchmarks'].items():
        table.append([benchmark_name, ])
        for name, value in values.items():
          if isinstance(value, (tuple, list)):
            value = "\n".join(value)
          elif isinstance(value, dict):
            value = tabulate(value.items(), tablefmt="plain")
          table.append([None, name, value])
      print(tabulate(table, tablefmt="grid"))
    if args.filter == "all" or args.filter == "probes":
      print(
          tabulate(data["probes"].items(),
                   headers=["Probe", "Help"],
                   tablefmt="grid"))


  def _setup_benchmark_subparser(self, benchmark_cls):
    subparser = benchmark_cls.add_cli_parser(self.subparsers)
    self.RUNNER_CLS.add_cli_parser(subparser)
    assert isinstance(subparser, argparse.ArgumentParser), (
        f"Benchmark class {benchmark_cls}.add_cli_parser did not return "
        f"an ArgumentParser: {subparser}")
    subparser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Don't run any browsers or probes")
    browser_group = subparser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--browser",
        help="Browser binary. Use this to test a single browser. "
        "Use a shortname [chrome, stable, dev, canary, safari] "
        "for system default browsers or a full path. "
        "Defaults to 'chrome'. "
        "Cannot be used with --browser-config")
    browser_group.add_argument(
        "--browser-config",
        type=pathlib.Path,
        help="Browser configuration.json file. "
        "Use this to run multiple browsers and/or multiple flag configurations."
        "See browser.config.example.hjson on how to set up a complex "
        "configuration file. "
        "Cannot be used together with --browser.")
    subparser.add_argument(
        "--probe",
        action="append",
        default=[],
        choices=self.GENERAL_PURPOSE_PROBES_BY_NAME.keys(),
        help="Enable general purpose probes to measure data on all cb.stories "
        "This argument can be specified multiple times to add more probes")
    subparser.add_argument("other_browser_args", nargs="*")
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
        default="")
    chrome_args.add_argument(
        "--disable-features",
        help="Command-separated list of disabled chrome features. " + DOC,
        default="")
    subparser.set_defaults(
        subcommand=self.benchmark_subcommand, benchmark_cls=benchmark_cls)

  def benchmark_subcommand(self, args):
    if args.browser_config:
      path = args.browser_config.expanduser()
      if not path.exists():
        raise argparse.ArgumentTypeError(
            f"Given path '{path.absolute}' does not exist")
      assert args.browser is None, (
          "Cannot specify --browser and --browser-config at the same time")
      with path.open() as f:
        args.browser_config = BrowserConfig.load(f)
    else:
      args.browser_config = BrowserConfig()
      args.browser_config.load_from_args(args)
    args.browsers = args.browser_config.variants

    benchmark_cls = args.benchmark_cls
    assert issubclass(benchmark_cls, cb.benchmarks.Benchmark), (
        f"benchmark_cls={benchmark_cls} is not subclass of Runner")
    benchmark = benchmark_cls(**benchmark_cls.kwargs_from_cli(args))

    runner_kwargs = self.RUNNER_CLS.kwargs_from_cli(args)
    runner  = self.RUNNER_CLS(benchmark=benchmark, **runner_kwargs)
    for probe_name in args.probe:
      probe = self.GENERAL_PURPOSE_PROBES_BY_NAME[probe_name]()
      runner.attach_probe(probe, matching_browser_only=True)
    runner.run(is_dry_run=args.dry_run)
    results_json = runner.out_dir / "results.json"
    print(f"RESULTS: {results_json}")

  def run(self, argv):
    args = self.parser.parse_args(argv)
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
