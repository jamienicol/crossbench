# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import itertools
import logging
import pathlib
import re
from enum import Enum
from typing import (TYPE_CHECKING, Any, Dict, Final, Iterable, List, Optional,
                    TextIO, Tuple, Type, Union)

import hjson

import crossbench.browsers.all as browsers
from crossbench import helper, cli_helper
from crossbench.browsers.browser import convert_flags_to_label
from crossbench.browsers.chrome import ChromeDownloader
from crossbench.env import HostEnvironment, HostEnvironmentConfig
from crossbench.exception import ExceptionAnnotator
from crossbench.flags import ChromeFlags, Flags
from crossbench.probes.all import GENERAL_PURPOSE_PROBES

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import Probe
  FlagGroupItemT = Optional[Tuple[str, Optional[str]]]
  BrowserLookupTableT = Dict[str, Tuple[Type[browsers.Browser], pathlib.Path]]


def _map_flag_group_item(flag_name: str,
                         flag_value: Optional[str]) -> FlagGroupItemT:
  if flag_value is None:
    return None
  if flag_value == "":
    return (flag_name, None)
  return (flag_name, flag_value)


class ConfigFileError(argparse.ArgumentTypeError):
  pass


class FlagGroupConfig:
  """This object corresponds to a flag-group in a configuration file.
  It contains mappings from flags to multiple values.
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

  def get_variant_items(self) -> Iterable[Tuple[FlagGroupItemT, ...]]:
    for flag_name, flag_values in self._variants.items():
      yield tuple(
          _map_flag_group_item(flag_name, flag_value)
          for flag_value in flag_values)


FlagItemT = Tuple[str, Optional[str]]


class BrowserDriverType(Enum):
  WEB_DRIVER = "WebDriver"
  APPLE_SCRIPT = "AppleScript"
  # TODO: implement additional drivers
  ANDROID = "Android"
  IOS = "iOS"

  @classmethod
  def default(cls) -> BrowserDriverType:
    return cls.WEB_DRIVER

  @classmethod
  def parse(cls, value: str) -> Tuple[BrowserDriverType, str]:
    # Early bail-out for windows-paths "C:/foo/bar" or driver-less inputs.
    if ":" not in value or pathlib.Path(value).exists():
      return cls.default(), value
    # Split inputs like "applescript:/out/x64.release/chrome"
    driver_name, _, path_or_identifier = value.partition(":")
    driver_name = driver_name.lower()
    if driver_name == "":
      return cls.default(), path_or_identifier
    if driver_name in ("", "selenium", "webdriver"):
      return cls.WEB_DRIVER, path_or_identifier
    if driver_name in ("applescript", "osa"):
      return cls.APPLE_SCRIPT, path_or_identifier
    if driver_name == "android":
      return cls.ANDROID, path_or_identifier
    if driver_name == "ios":
      return cls.IOS, path_or_identifier

    raise argparse.ArgumentTypeError(f"Unknown driver type: {driver_name}")


class BrowserConfig:

  @classmethod
  def from_cli_args(cls, args: argparse.Namespace) -> BrowserConfig:
    browser_config = BrowserConfig()
    if args.browser_config:
      with cli_helper.late_argument_type_error_wrapper("--browser-config"):
        path = args.browser_config.expanduser()
        with path.open(encoding="utf-8") as f:
          browser_config.load(f)
    else:
      with cli_helper.late_argument_type_error_wrapper("--browser"):
        browser_config.load_from_args(args)
    return browser_config

  def __init__(self,
               raw_config_data: Optional[Dict[str, Any]] = None,
               browser_lookup_override: Optional[BrowserLookupTableT] = None):
    self.flag_groups: Dict[str, FlagGroupConfig] = {}
    self._variants: List[Browser] = []
    self._browser_lookup_override = browser_lookup_override or {}
    self._cache_dir: pathlib.Path = browsers.BROWSERS_CACHE
    self._exceptions = ExceptionAnnotator()
    if raw_config_data:
      self.load_dict(raw_config_data)

  @property
  def variants(self) -> List[Browser]:
    self._exceptions.assert_success(
        "Could not create variants from config files: {}", ConfigFileError)
    return self._variants

  def load(self, f: TextIO) -> None:
    with self._exceptions.capture(f"Loading browser config file: {f.name}"):
      config = {}
      with self._exceptions.info(f"Parsing {hjson.__name__}"):
        config = hjson.load(f)
      with self._exceptions.info(f"Parsing config file: {f.name}"):
        self.load_dict(config)

  def load_dict(self, raw_config_data: Dict[str, Any]) -> None:
    try:
      if "flags" in raw_config_data:
        with self._exceptions.info("Parsing config['flags']"):
          self._parse_flag_groups(raw_config_data["flags"])
      if "browsers" not in raw_config_data:
        raise ConfigFileError("Config does not provide a 'browsers' dict.")
      if not raw_config_data["browsers"]:
        raise ConfigFileError("Config contains empty 'browsers' dict.")
      with self._exceptions.info("Parsing config['browsers']"):
        self._parse_browsers(raw_config_data["browsers"])
    except Exception as e:  # pylint: disable=broad-except
      self._exceptions.append(e)

  def load_from_args(self, args: argparse.Namespace) -> None:
    self._cache_dir = args.cache_dir
    browser_list = args.browser or ["chrome-stable"]
    assert isinstance(browser_list, list)
    if len(browser_list) != len(set(browser_list)):
      raise argparse.ArgumentTypeError(
          f"Got duplicate --browser arguments: {browser_list}")
    for browser in browser_list:
      self._append_browser(args, browser)
    self._verify_browser_flags(args)
    self._ensure_unique_browser_names()

  def _parse_flag_groups(self, data: Dict[str, Any]) -> None:
    for flag_name, group_config in data.items():
      with self._exceptions.capture(
          f"Parsing flag-group: flags['{flag_name}']"):
        self._parse_flag_group(flag_name, group_config)

  def _parse_flag_group(self, name: str,
                        raw_flag_group_data: Dict[str, Any]) -> None:
    if name in self.flag_groups:
      raise ConfigFileError(f"flag-group flags['{name}'] exists already")
    variants: Dict[str, List[str]] = {}
    for flag_name, values in raw_flag_group_data.items():
      if not flag_name.startswith("-"):
        raise ConfigFileError(f"Invalid flag name: '{flag_name}'")
      if flag_name not in variants:
        flag_values = variants[flag_name] = []
      else:
        flag_values = variants[flag_name]
      if isinstance(values, str):
        values = [values]
      for value in values:
        if value == "None,":
          raise ConfigFileError(
              f"Please use null instead of None for flag '{flag_name}' ")
        # O(n^2) check, assuming very few values per flag.
        if value in flag_values:
          raise ConfigFileError(
              "Same flag variant was specified more than once: "
              f"'{value}' for entry '{flag_name}'")
        flag_values.append(value)
    self.flag_groups[name] = FlagGroupConfig(name, variants)

  def _parse_browsers(self, data: Dict[str, Any]) -> None:
    for name, browser_config in data.items():
      with self._exceptions.info(f"Parsing browsers['{name}']"):
        self._parse_browser(name, browser_config)
    self._ensure_unique_browser_names()

  def _parse_browser(self, name: str, raw_browser_data: Dict[str, Any]) -> None:
    path_or_identifier: str = raw_browser_data["path"]
    if path_or_identifier in self._browser_lookup_override:
      browser_cls, path = self._browser_lookup_override[path_or_identifier]
    else:
      path, driver_type = self._parse_browser_path_and_driver(
          path_or_identifier)
      browser_cls = self._get_browser_cls(path, driver_type)
    if not path.exists():
      raise ConfigFileError(f"browsers['{name}'].path='{path}' does not exist.")
    raw_flags: List[Tuple[FlagItemT, ...]] = []
    with self._exceptions.info(f"Parsing browsers['{name}'].flags"):
      raw_flags = self._parse_flags(name, raw_browser_data)
    variants_flags: Tuple[Flags, ...] = ()
    with self._exceptions.info(
        f"Expand browsers['{name}'].flags into full variants"):
      variants_flags = tuple(
          browser_cls.default_flags(flags) for flags in raw_flags)
    logging.info("SELECTED BROWSER: '%s' with %s flag variants:", name,
                 len(variants_flags))
    for i in range(len(variants_flags)):
      logging.info("   %s: %s", i, variants_flags[i])
    # pytype: disable=not-instantiable
    self._variants += [
        browser_cls(
            label=self._flags_to_label(name, flags), path=path, flags=flags)
        for flags in variants_flags
    ]
    # pytype: enable=not-instantiable

  def _flags_to_label(self, name: str, flags: Flags) -> str:
    return f"{name}_{convert_flags_to_label(*flags.get_list())}"

  def _parse_flags(self, name: str,
                   data: Dict[str, Any]) -> List[Tuple[FlagItemT, ...]]:
    flags_variants: List[Tuple[FlagGroupItemT, ...]] = []
    flag_group_names = data.get("flags", [])
    if isinstance(flag_group_names, str):
      flag_group_names = [flag_group_names]
    if not isinstance(flag_group_names, list):
      raise ConfigFileError(f"'flags' is not a list for browser='{name}'")
    seen_flag_group_names = set()
    for flag_group_name in flag_group_names:
      if flag_group_name in seen_flag_group_names:
        raise ConfigFileError(
            f"Duplicate group name '{flag_group_name}' for browser='{name}'")
      seen_flag_group_names.add(flag_group_name)
      # Use temporary FlagGroupConfig for inline fixed flag definition
      if flag_group_name.startswith("--"):
        flag_name, flag_value = Flags.split(flag_group_name)
        # No-value-flags produce flag_value == None, convert this to the "" for
        # compatibility with the flag variants, where None would mean removing
        # the flag.
        if flag_value is None:
          flag_value = ""
        flag_group = FlagGroupConfig("temporary", {flag_name: flag_value})
        assert flag_group_name not in self.flag_groups
      else:
        flag_group = self.flag_groups.get(flag_group_name, None)
        if flag_group is None:
          raise ConfigFileError(f"group='{flag_group_name}' "
                                f"for browser='{name}' does not exist.")
      flags_variants += flag_group.get_variant_items()
    if len(flags_variants) == 0:
      # use empty default
      return [tuple()]
    # IN:  [
    #   (None,            ("--foo", "f1")),
    #   (("--bar", "b1"), ("--bar", "b2")),
    # ]
    # OUT: [
    #   (None,            ("--bar", "b1")),
    #   (None,            ("--bar", "b2")),
    #   (("--foo", "f1"), ("--bar", "b1")),
    #   (("--foo", "f1"), ("--bar", "b2")),
    # ]:
    flags_variants_combinations = list(itertools.product(*flags_variants))
    # IN: [
    #   (None,            None)
    #   (None,            ("--foo", "f1")),
    #   (("--foo", "f1"), ("--bar", "b1")),
    # ]
    # OUT: [
    #   (("--foo", "f1"),),
    #   (("--foo", "f1"), ("--bar", "b1")),
    # ]
    #
    flags_variants_filtered = list(
        tuple(flag_item
              for flag_item in flags_items
              if flag_item is not None)
        for flags_items in flags_variants_combinations)
    assert flags_variants_filtered
    return flags_variants_filtered

  def _get_browser_cls(self, path: pathlib.Path,
                       driver: BrowserDriverType) -> Type[Browser]:
    path_str = str(path).lower()
    if "safari" in path_str:
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.SafariWebDriver
      if driver == BrowserDriverType.APPLE_SCRIPT:
        return browsers.SafariAppleScript
    if "chrome" in path_str:
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.ChromeWebDriver
      if driver == BrowserDriverType.APPLE_SCRIPT:
        return browsers.ChromeAppleScript
    if "chromium" in path_str:
      # TODO: technically this should be ChromiumWebDriver
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.ChromeWebDriver
      if driver == BrowserDriverType.APPLE_SCRIPT:
        return browsers.ChromeAppleScript
    if "firefox" in path_str:
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.FirefoxWebDriver
    if "edge" in path_str:
      return browsers.EdgeWebDriver
    raise argparse.ArgumentTypeError(f"Unsupported browser='{path}'")

  def _ensure_unique_browser_names(self) -> None:
    if self._has_unique_variant_names():
      return
    # Expand to full version names
    for browser in self._variants:
      browser.unique_name = f"{browser.type}_{browser.version}_{browser.label}"
    if self._has_unique_variant_names():
      return
    logging.info("Got unique browser names and versions, "
                 "please use --browser-config for more meaningful names")
    # Last resort, add index
    for index, browser in enumerate(self._variants):
      browser.unique_name += f"_{index}"
    assert self._has_unique_variant_names()

  def _has_unique_variant_names(self) -> bool:
    names = [browser.unique_name for browser in self._variants]
    unique_names = set(names)
    return len(unique_names) == len(names)

  def _verify_browser_flags(self, args: argparse.Namespace) -> None:
    chrome_args = {
        "--enable-features": args.enable_features,
        "--disable-features": args.disable_features,
        "--js-flags": args.js_flags
    }
    for flag_name, value in chrome_args.items():
      if not value:
        continue
      for browser in self._variants:
        if not isinstance(browser, browsers.Chromium):
          raise argparse.ArgumentTypeError(
              f"Used chrome/chromium-specific flags {flag_name} "
              f"for non-chrome {browser.unique_name}.\n"
              "Use --browser-config for complex variants.")
    if not args.other_browser_args:
      return
    browser_types = set(browser.type for browser in self._variants)
    if len(browser_types) > 1:
      raise argparse.ArgumentTypeError(
          f"Multiple browser types {browser_types} "
          "cannot be used with common extra browser flags: "
          f"{args.other_browser_args}.\n"
          "Use --browser-config for complex variants.")

  def _append_browser(self, args: argparse.Namespace, browser: str) -> None:
    assert browser, "Expected non-empty browser name"
    path, driver_type = self._parse_browser_path_and_driver(browser)
    browser_cls = self._get_browser_cls(path, driver_type)
    flags = browser_cls.default_flags()

    if issubclass(browser_cls, browsers.Chromium):
      assert isinstance(flags, ChromeFlags)
      self._init_chrome_flags(args, flags)

    for flag_str in args.other_browser_args:
      flag_name, flag_value = Flags.split(flag_str)
      flags.set(flag_name, flag_value)

    label = convert_flags_to_label(*flags.get_list())
    browser_instance = browser_cls(  # pytype: disable=not-instantiable
        label=label,
        path=path,
        flags=flags,
        viewport=args.viewport,
        splash_screen=args.splash_screen)
    logging.info("SELECTED BROWSER: name=%s path='%s' ",
                 browser_instance.unique_name, path)
    self._variants.append(browser_instance)

  def _init_chrome_flags(self, args: argparse.Namespace,
                         flags: ChromeFlags) -> None:
    if args.enable_features:
      for feature in args.enable_features.split(","):
        flags.features.enable(feature)
    if args.disable_features:
      for feature in args.disable_features.split(","):
        flags.features.disable(feature)
    if args.js_flags:
      for js_flag in args.js_flags.split(","):
        js_flag_name, js_flag_value = Flags.split(js_flag.lstrip())
        flags.js_flags.set(js_flag_name, js_flag_value)

  def _parse_browser_path_and_driver(
      self, value: str) -> Tuple[pathlib.Path, BrowserDriverType]:
    driver, maybe_path_or_identifier = BrowserDriverType.parse(value)
    identifier = maybe_path_or_identifier.lower()
    # We're not using a dict-based lookup here, since not all browsers are
    # available on all platforms
    if identifier in ("chrome", "chrome-stable", "chr-stable", "chr"):
      return browsers.Chrome.stable_path(), driver
    if identifier in ("chrome-beta", "chr-beta"):
      return browsers.Chrome.beta_path(), driver
    if identifier in ("chrome-dev", "chr-dev"):
      return browsers.Chrome.dev_path(), driver
    if identifier in ("chrome-canary", "chr-canary"):
      return browsers.Chrome.canary_path(), driver
    if identifier in ("edge", "edge-stable"):
      return browsers.Edge.stable_path(), driver
    if identifier == "edge-beta":
      return browsers.Edge.beta_path(), driver
    if identifier == "edge-dev":
      return browsers.Edge.dev_path(), driver
    if identifier == "edge-canary":
      return browsers.Edge.canary_path(), driver
    if identifier in ("safari", "sf"):
      return browsers.Safari.default_path(), driver
    if identifier in ("safari-technology-preview", "safari-tp", "sf-tp", "tp"):
      return browsers.Safari.technology_preview_path(), driver
    if identifier in ("firefox", "ff"):
      return browsers.Firefox.default_path(), driver
    if identifier in ("firefox-dev", "firefox-developer-edition", "ff-dev"):
      return browsers.Firefox.developer_edition_path(), driver
    if identifier in ("firefox-nightly", "ff-nightly", "ff-trunk"):
      return browsers.Firefox.nightly_path(), driver
    platform = helper.PLATFORM
    if ChromeDownloader.is_valid(value, platform):
      return ChromeDownloader.load(
          value, platform, cache_dir=self._cache_dir), driver
    path = pathlib.Path(maybe_path_or_identifier)
    if path.exists():
      return path, driver
    path = path.expanduser()
    if path.exists():
      return path, driver
    if len(path.parts) > 1:
      raise argparse.ArgumentTypeError(f"Browser at '{path}' does not exist.")
    raise argparse.ArgumentTypeError(
        f"Unknown browser path or short name: '{value}'")


class ProbeConfigError(argparse.ArgumentTypeError):
  pass


class ProbeConfig:

  LOOKUP: Dict[str,
               Type[Probe]] = {cls.NAME: cls for cls in GENERAL_PURPOSE_PROBES}

  _PROBE_RE: Final[re.Pattern] = re.compile(
      r"(?P<probe_name>[\w.]+)(:?(?P<config>\{.*\}))?",
      re.MULTILINE | re.DOTALL)

  @classmethod
  def from_cli_args(cls, args: argparse.Namespace) -> ProbeConfig:
    if args.probe_config:
      with args.probe_config.open(encoding="utf-8") as f:
        return cls.load(f, throw=args.throw)
    return cls(args.probe, throw=args.throw)

  @classmethod
  def load(cls, file: TextIO, throw: bool = False) -> ProbeConfig:
    probe_config = cls(throw=throw)
    probe_config.load_config_file(file)
    return probe_config

  def __init__(self,
               probe_names_with_args: Optional[Iterable[str]] = None,
               throw: bool = False):
    self._exceptions = ExceptionAnnotator(throw=throw)
    self._probes: List[Probe] = []
    if not probe_names_with_args:
      return
    for probe_name_with_args in probe_names_with_args:
      with self._exceptions.capture(f"Parsing --probe={probe_name_with_args}"):
        self.add_probe(probe_name_with_args)

  @property
  def probes(self) -> List[Probe]:
    self._exceptions.assert_success("Could not load probes: {}",
                                    ConfigFileError)
    return self._probes

  def add_probe(self, probe_name_with_args: str) -> None:
    # Look for probes with json payload:
    # - "ProbeName{json_key:json_value, ...}"
    # - "ProbeName:{json_key:json_value, ...}"
    inline_config = {}
    match = self._PROBE_RE.fullmatch(probe_name_with_args)
    if match is None:
      raise ProbeConfigError(
          f"Could not parse probe argument: {probe_name_with_args}")
    if match["config"]:
      probe_name = match["probe_name"]
      json_args = match["config"]
      assert json_args[0] == "{" and json_args[-1] == "}"
      try:
        inline_config = hjson.loads(json_args)
      except ValueError as e:
        message = (f"Could not decode inline probe config: {json_args}\n"
                   f"   {str(e)}")
        if "eof" in message:
          message += "\n   Likely missing quotes for --probe argument."
        raise ProbeConfigError(message) from e
    else:
      # Default case without the additional hjson payload
      probe_name = match["probe_name"]
    if probe_name not in self.LOOKUP:
      self.raise_unknown_probe(probe_name)
    with self._exceptions.info(
        f"Parsing inline probe config: {probe_name}",
        f"  Use 'describe probe {probe_name}' for more details"):
      probe_cls: Type[Probe] = self.LOOKUP[probe_name]
      probe: Probe = probe_cls.from_config(
          inline_config, throw=self._exceptions.throw)
      self._probes.append(probe)

  def load_config_file(self, file: TextIO) -> None:
    with self._exceptions.capture(f"Loading probe config file: {file.name}"):
      data = None
      with self._exceptions.info(f"Parsing {hjson.__name__}"):
        try:
          data = hjson.load(file)
        except ValueError as e:
          raise ProbeConfigError(f"Parsing error: {e}") from e
      if not isinstance(data, dict) or "probes" not in data:
        raise ProbeConfigError(
            "Probe config file does not contain a 'probes' dict value.")
      self.load_dict(data["probes"])

  def load_dict(self, data: Dict[str, Any]) -> None:
    for probe_name, config_data in data.items():
      with self._exceptions.info(
          f"Parsing probe config probes['{probe_name}']"):
        if probe_name not in self.LOOKUP:
          self.raise_unknown_probe(probe_name)
        probe_cls = self.LOOKUP[probe_name]
        self._probes.append(probe_cls.from_config(config_data))

  def raise_unknown_probe(self, probe_name: str) -> None:
    additional_msg = ""
    if ":" in probe_name or "}" in probe_name:
      additional_msg = "\n    Likely missing quotes for --probe argument"
    msg = f"    Options are: {list(self.LOOKUP.keys())}{additional_msg}"
    raise ProbeConfigError(f"Unknown probe name: '{probe_name}'\n{msg}")


def parse_inline_env_config(value: str) -> HostEnvironmentConfig:
  if value in HostEnvironment.CONFIGS:
    return HostEnvironment.CONFIGS[value]
  if value[0] != "{":
    raise argparse.ArgumentTypeError(
        f"Invalid env config name: '{value}'. "
        f"choices = {list(HostEnvironment.CONFIGS.keys())}")
  # Assume hjson data
  kwargs = None
  msg = ""
  try:
    kwargs = hjson.loads(value)
    return HostEnvironmentConfig(**kwargs)
  except Exception as e:
    msg = f"\n{e}"
    raise argparse.ArgumentTypeError(
        f"Invalid inline config string: {value}{msg}") from e


def parse_env_config_file(value: str) -> HostEnvironmentConfig:
  config_path: pathlib.Path = cli_helper.parse_file_path(value)
  try:
    with config_path.open(encoding="utf-8") as f:
      data = hjson.load(f)
    if "env" not in data:
      raise argparse.ArgumentTypeError("No 'env' property found")
    kwargs = data["env"]
    return HostEnvironmentConfig(**kwargs)
  except Exception as e:
    msg = f"\n{e}"
    raise argparse.ArgumentTypeError(
        f"Invalid env config file: {value}{msg}") from e
