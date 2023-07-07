# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import argparse
import dataclasses
import itertools
import logging
import pathlib
import re
from typing import (TYPE_CHECKING, Any, Dict, Final, Iterable, List, Optional,
                    TextIO, Tuple, Type, Union)

import hjson

import crossbench.browsers.all as browsers
from crossbench import cli_helper, exception, helper
from crossbench.browsers.browser import convert_flags_to_label
from crossbench.browsers.chrome import ChromeDownloader
from crossbench.config import ConfigObject, ConfigParser
from crossbench.env import HostEnvironment, HostEnvironmentConfig
from crossbench.exception import ExceptionAnnotator
from crossbench.flags import ChromeFlags, Flags
from crossbench import platform
from crossbench.probes.all import GENERAL_PURPOSE_PROBES

if TYPE_CHECKING:
  from crossbench.browsers.browser import Browser
  from crossbench.probes.probe import Probe
  FlagGroupItemT = Optional[Tuple[str, Optional[str]]]


def _map_flag_group_item(flag_name: str,
                         flag_value: Optional[str]) -> FlagGroupItemT:
  if flag_value is None:
    return None
  if flag_value == "":
    return (flag_name, None)
  return (flag_name, flag_value)


def parse_inline_hjson(value: str) -> Any:
  if value[0] != "{" or value[-1] != "}":
    raise argparse.ArgumentTypeError(
        f"Invalid inline {hjson.__name__}, missing braces: '{value}'")
  try:
    return hjson.loads(value)
  except ValueError as e:
    message = _extract_decoding_error(value, e)
    if "eof" in message:
      message += "\n   Likely missing quotes."
    raise argparse.ArgumentTypeError(message) from e


def _extract_decoding_error(value: str, e: ValueError) -> str:
  lineno = getattr(e, "lineno", -1) - 1
  colno = getattr(e, "colno", -1) - 1
  decode_message = "Could not decode inline config"
  if lineno < 0 or colno < 0:
    return f"{decode_message}: {value}\n    {str(e)}"
  line = value.splitlines()[lineno - 1]
  marker = (" " * colno) + "^"
  return f"{decode_message}\n    {line}\n    {marker}\n({str(e)})"


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


class BrowserDriverType(helper.EnumWithHelp):
  WEB_DRIVER = ("WebDriver", "Use Selenium with webdriver, for local runs.")
  APPLE_SCRIPT = ("AppleScript", "Use AppleScript, for local macOS runs only")
  # TODO: implement additional drivers
  ANDROID = ("Android",
             "Use Webdriver for android. Allows to specify additional settings")
  IOS = ("iOS", "Placeholder, unsupported at the moment")

  @classmethod
  def default(cls) -> BrowserDriverType:
    return cls.WEB_DRIVER

  @classmethod
  def parse(cls, value: str) -> BrowserDriverType:
    identifier = value.lower()
    if identifier == "":
      return BrowserDriverType.default()
    if identifier in ("", "selenium", "webdriver"):
      return BrowserDriverType.WEB_DRIVER
    if identifier in ("applescript", "osa"):
      return BrowserDriverType.APPLE_SCRIPT
    if identifier in ("android", "adb"):
      return BrowserDriverType.ANDROID
    if identifier == "ios":
      return BrowserDriverType.IOS
    raise argparse.ArgumentTypeError(f"Unknown driver type: {identifier}")


def try_resolve_existing_path(value: str) -> Optional[pathlib.Path]:
  if not value:
    return None
  maybe_path = pathlib.Path(value)
  if maybe_path.exists():
    return maybe_path
  maybe_path = maybe_path.expanduser()
  if maybe_path.exists():
    return maybe_path
  return None


@dataclasses.dataclass(frozen=True)
class DriverConfig(ConfigObject):
  type: BrowserDriverType = BrowserDriverType.default()
  path: Optional[pathlib.Path] = None
  settings: Optional[Any] = None

  @classmethod
  def default(cls) -> DriverConfig:
    return cls(BrowserDriverType.default())

  @classmethod
  def loads(cls, value: str) -> DriverConfig:
    if not value:
      raise argparse.ArgumentTypeError("Cannot parse empty string")
    # Variant 1: $PATH
    path: Optional[pathlib.Path] = try_resolve_existing_path(value)
    driver_type: BrowserDriverType = BrowserDriverType.default()
    if not path:
      # Variant 2: $DRIVER_TYPE
      if "{" != value[0]:
        driver_type = BrowserDriverType.parse(value)
      else:
        # Variant 2: full hjson config
        data = parse_inline_hjson(value)
        return cls.load_dict(data)
    if path and path.stat().st_size == 0:
      raise argparse.ArgumentTypeError(f"Driver path is empty file: {path}")
    return DriverConfig(driver_type, path)

  @classmethod
  def load_dict(cls,
                config: Dict[str, Any],
                throw: bool = False) -> DriverConfig:
    return cls.config_parser().parse(config, throw)

  @classmethod
  def config_parser(cls) -> ConfigParser[DriverConfig]:
    parser = ConfigParser("DriverConfig parser", cls)
    parser.add_argument("type", type=BrowserDriverType.parse)
    parser.add_argument(
        "settings",
        type=dict,
        help="Additional driver settings (Driver dependent).")
    return parser


SUPPORTED_BROWSER = ("chromium", "chrome", "safari", "edge", "firefox")

@dataclasses.dataclass(frozen=True)
class BrowserConfig(ConfigObject):
  browser: Union[pathlib.Path, str]
  driver: DriverConfig = DriverConfig.default()

  @classmethod
  def default(cls) -> BrowserConfig:
    return cls(browsers.Chrome.stable_path(), DriverConfig.default())

  @classmethod
  def loads(cls, value: str) -> BrowserConfig:
    if not value:
      raise argparse.ArgumentTypeError("Cannot parse empty string")
    driver = DriverConfig.default()
    path: Optional[Union[pathlib.Path, str]] = None
    if ":" not in value:
      # Variant 1: $PATH_OR_IDENTIFIER
      path = cls._parse_path_or_identifier(value)
    elif value[0] != "{":
      # Variant 2: ${DRIVER_TYPE}:${PATH_OR_IDENTIFIER
      driver, path = cls._parse_inline_driver(value)
    else:
      # Variant 3: Full inline hjson
      config = parse_inline_hjson(value)
      with exception.annotate(f"Parsing inline {cls.__name__}"):
        return cls.load_dict(config)
    assert path, "Invalid path"
    return cls(path, driver)

  @classmethod
  def _parse_path_or_identifier(
      cls,
      maybe_path_or_identifier: str,
      driver_type: Optional[BrowserDriverType] = None
  ) -> Union[str, pathlib.Path]:
    identifier = maybe_path_or_identifier.lower()
    driver_type = driver_type or BrowserDriverType.default()
    # We're not using a dict-based lookup here, since not all browsers are
    # available on all platforms
    if identifier in ("chrome", "chrome-stable", "chr-stable", "chr"):
      if driver_type == BrowserDriverType.ANDROID:
        return pathlib.Path("com.android.chrome")
      return browsers.Chrome.stable_path()
    if identifier in ("chrome-beta", "chr-beta"):
      if driver_type == BrowserDriverType.ANDROID:
        return pathlib.Path("com.chrome.beta")
      return browsers.Chrome.beta_path()
    if identifier in ("chrome-dev", "chr-dev"):
      if driver_type == BrowserDriverType.ANDROID:
        return pathlib.Path("com.chrome.dev")
      return browsers.Chrome.dev_path()
    if identifier in ("chrome-canary", "chr-canary"):
      if driver_type == BrowserDriverType.ANDROID:
        return pathlib.Path("com.chrome.canary")
      return browsers.Chrome.canary_path()
    if identifier in ("edge", "edge-stable"):
      return browsers.Edge.stable_path()
    if identifier == "edge-beta":
      return browsers.Edge.beta_path()
    if identifier == "edge-dev":
      return browsers.Edge.dev_path()
    if identifier == "edge-canary":
      return browsers.Edge.canary_path()
    if identifier in ("safari", "sf"):
      return browsers.Safari.default_path()
    if identifier in ("safari-technology-preview", "safari-tp", "sf-tp", "tp"):
      return browsers.Safari.technology_preview_path()
    if identifier in ("firefox", "ff"):
      return browsers.Firefox.default_path()
    if identifier in ("firefox-dev", "firefox-developer-edition", "ff-dev"):
      return browsers.Firefox.developer_edition_path()
    if identifier in ("firefox-nightly", "ff-nightly", "ff-trunk"):
      return browsers.Firefox.nightly_path()
    if ChromeDownloader.is_valid(maybe_path_or_identifier, platform.PLATFORM):
      # We have a valid version identifier for chrome.
      return maybe_path_or_identifier
    path = try_resolve_existing_path(maybe_path_or_identifier)
    if not path:
      raise argparse.ArgumentTypeError(
          f"Unknown browser path or short name: '{maybe_path_or_identifier}'")
    if cls.is_supported_browser_path(path):
      return path
    raise argparse.ArgumentTypeError(f"Unsupported browser path='{path}'")

  @classmethod
  def is_supported_browser_path(cls, path: pathlib.Path):
    path_str = str(path).lower()
    for short_name in SUPPORTED_BROWSER:
      if short_name in path_str:
        return True
    return False

  @classmethod
  def _parse_inline_driver(
      cls, value: str) -> Tuple[DriverConfig, Union[str, pathlib.Path]]:
    # Split inputs like "applescript:/out/x64.release/chrome"
    driver_path_or_identifier, _, path_or_identifier = value.partition(":")
    driver = DriverConfig.parse(driver_path_or_identifier)
    path: Union[str, pathlib.Path] = cls._parse_path_or_identifier(
        path_or_identifier, driver.type)
    return (driver, path)

  @classmethod
  def load(cls, f: TextIO) -> BrowserConfig:
    with exception.annotate(f"Loading browser config file: {f.name}"):
      config = {}
      with exception.annotate(f"Parsing {hjson.__name__}"):
        config = hjson.load(f)
      with exception.annotate(f"Parsing config file: {f.name}"):
        return cls.load_dict(config)
    raise argparse.ArgumentTypeError(f"Could not parse : '{f.name}'")

  @classmethod
  def load_dict(cls,
                config: Dict[str, Any],
                throw: bool = False) -> BrowserConfig:
    return cls.config_parse().parse(config, throw)

  @classmethod
  def config_parse(cls) -> ConfigParser[BrowserConfig]:
    parser = ConfigParser("BrowserConfig parser", cls)
    parser.add_argument("browser", type=cls._parse_path_or_identifier)
    parser.add_argument("driver", type=DriverConfig.parse)
    return parser

  @property
  def path(self) -> pathlib.Path:
    assert isinstance(self.browser, pathlib.Path)
    return self.browser


BrowserLookupTableT = Dict[str, Tuple[Type[browsers.Browser], BrowserConfig]]


class BrowserVariantsConfig:

  @classmethod
  def from_cli_args(cls, args: argparse.Namespace) -> BrowserVariantsConfig:
    browser_config = BrowserVariantsConfig()
    if args.browser_config:
      with cli_helper.late_argument_type_error_wrapper("--browser-config"):
        path = args.browser_config.expanduser()
        with path.open(encoding="utf-8") as f:
          browser_config.load(f, args)
    else:
      with cli_helper.late_argument_type_error_wrapper("--browser"):
        browser_config.load_from_args(args)
    return browser_config

  def __init__(self,
               raw_config_data: Optional[Dict[str, Any]] = None,
               browser_lookup_override: Optional[BrowserLookupTableT] = None,
               args: Optional[argparse.Namespace] = None):
    self.flag_groups: Dict[str, FlagGroupConfig] = {}
    self._variants: List[Browser] = []
    self._browser_lookup_override = browser_lookup_override or {}
    self._cache_dir: pathlib.Path = browsers.BROWSERS_CACHE
    self._exceptions = ExceptionAnnotator()
    if raw_config_data:
      assert args, "args object needed when loading from dict."
      self.load_dict(raw_config_data, args)

  @property
  def variants(self) -> List[Browser]:
    self._exceptions.assert_success(
        "Could not create variants from config files: {}", ConfigFileError)
    return self._variants

  def load(self, f: TextIO, args: argparse.Namespace) -> None:
    with self._exceptions.capture(f"Loading browser config file: {f.name}"):
      config = {}
      with self._exceptions.info(f"Parsing {hjson.__name__}"):
        config = hjson.load(f)
      with self._exceptions.info(f"Parsing config file: {f.name}"):
        self.load_dict(config, args)

  def load_dict(self, config: Dict[str, Any], args: argparse.Namespace) -> None:
    try:
      if "flags" in config:
        with self._exceptions.info("Parsing config['flags']"):
          self._parse_flag_groups(config["flags"])
      if "browsers" not in config:
        raise ConfigFileError("Config does not provide a 'browsers' dict.")
      if not config["browsers"]:
        raise ConfigFileError("Config contains empty 'browsers' dict.")
      with self._exceptions.info("Parsing config['browsers']"):
        self._parse_browsers(config["browsers"], args)
    except Exception as e:  # pylint: disable=broad-except
      self._exceptions.append(e)

  def load_from_args(self, args: argparse.Namespace) -> None:
    self._cache_dir = args.cache_dir
    browser_list: List[BrowserConfig] = args.browser or [
        BrowserConfig.default()
    ]
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

  def _parse_browsers(self, data: Dict[str, Any],
                      args: argparse.Namespace) -> None:
    for name, browser_config in data.items():
      with self._exceptions.info(f"Parsing browsers['{name}']"):
        self._parse_browser(name, browser_config, args)
    self._ensure_unique_browser_names()

  def _parse_browser(self, name: str, raw_browser_data: Dict[str, Any],
                     args: argparse.Namespace) -> None:
    # TODO: turn this into a dispatching sub-parser
    path_or_identifier: str = raw_browser_data["path"]
    browser_cls: Type[Browser]
    if path_or_identifier in self._browser_lookup_override:
      browser_cls, browser_config = self._browser_lookup_override[
          path_or_identifier]
    else:
      browser_config = self._maybe_downloaded_binary(
          BrowserConfig.parse(path_or_identifier))
      browser_cls = self._get_browser_cls(browser_config)
    if browser_config.driver.type != BrowserDriverType.ANDROID and (
        not browser_config.path.exists()):
      raise ConfigFileError(
          f"browsers['{name}'].path='{browser_config.path}' does not exist.")
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
    browser_platform = self._get_browser_platform(browser_config)
    for flags in variants_flags:
      # pytype: disable=not-instantiable
      browser_instance = browser_cls(
          label=self._flags_to_label(name, flags),
          path=browser_config.path,
          flags=flags,
          driver_path=args.driver_path or browser_config.driver.path,
          # TODO: support all args in the browser.config file
          viewport=args.viewport,
          splash_screen=args.splash_screen,
          platform=browser_platform)
      # pytype: enable=not-instantiable
      self._variants.append(browser_instance)

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
                                f"for browser='{name}' does not exist.\n"
                                f"Choices are: {list(self.flag_groups.keys())}")
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

  def _get_browser_cls(self, browser_config: BrowserConfig) -> Type[Browser]:
    driver = browser_config.driver.type
    path = browser_config.path
    assert not isinstance(path, str), "Invalid path"
    if not BrowserConfig.is_supported_browser_path(path):
      raise argparse.ArgumentTypeError(f"Unsupported browser path='{path}'")
    path_str = str(browser_config.path).lower()
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
      if driver == BrowserDriverType.ANDROID:
        return browsers.ChromeWebDriverAndroid
    if "chromium" in path_str:
      # TODO: technically this should be ChromiumWebDriver
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.ChromeWebDriver
      if driver == BrowserDriverType.APPLE_SCRIPT:
        return browsers.ChromeAppleScript
      if driver == BrowserDriverType.ANDROID:
        return browsers.ChromiumWebDriverAndroid
    if "firefox" in path_str:
      if driver == BrowserDriverType.WEB_DRIVER:
        return browsers.FirefoxWebDriver
    if "edge" in path_str:
      return browsers.EdgeWebDriver
    raise argparse.ArgumentTypeError(f"Unsupported browser path='{path}'")

  def _get_browser_platform(self,
                            browser_config: BrowserConfig) -> platform.Platform:
    # TODO: support more custom platform properties (serial-id...)
    if browser_config.driver.type == BrowserDriverType.ANDROID:
      return platform.AndroidAdbPlatform(platform.PLATFORM)
    return platform.PLATFORM

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
    browser_types = set(browser.type for browser in self._variants)
    if len(browser_types) == 1:
      return
    if args.driver_path:
      raise argparse.ArgumentTypeError(
          f"Cannot use custom --driver-path='{args.driver_path}' "
          f"for multiple browser {browser_types}.")
    if args.other_browser_args:
      raise argparse.ArgumentTypeError(
          f"Multiple browser types {browser_types} "
          "cannot be used with common extra browser flags: "
          f"{args.other_browser_args}.\n"
          "Use --browser-config for complex variants.")

  def _maybe_downloaded_binary(self,
                               browser_config: BrowserConfig) -> BrowserConfig:
    if browser_config.driver.type == BrowserDriverType.ANDROID:
      return browser_config
    path_or_identifier = browser_config.browser
    if isinstance(path_or_identifier, pathlib.Path):
      return browser_config
    downloaded = ChromeDownloader.load(
        path_or_identifier, platform.PLATFORM, cache_dir=self._cache_dir)
    return BrowserConfig(downloaded, browser_config.driver)

  def _append_browser(self, args: argparse.Namespace,
                      browser_config: BrowserConfig) -> None:
    assert browser_config, "Expected non-empty BrowserConfig."
    browser_config = self._maybe_downloaded_binary(browser_config)
    browser_cls: Type[Browser] = self._get_browser_cls(browser_config)
    path: pathlib.Path = browser_config.path
    flags = browser_cls.default_flags()

    if browser_config.driver.type != BrowserDriverType.ANDROID and (
        not path.exists()):
      raise argparse.ArgumentTypeError(f"Browser binary does not exist: {path}")

    if issubclass(browser_cls, browsers.Chromium):
      assert isinstance(flags, ChromeFlags)
      self._init_chrome_flags(args, flags)

    for flag_str in args.other_browser_args:
      flag_name, flag_value = Flags.split(flag_str)
      flags.set(flag_name, flag_value)

    label = convert_flags_to_label(*flags.get_list())
    browser_platform = self._get_browser_platform(browser_config)
    browser_instance = browser_cls(  # pytype: disable=not-instantiable
        label=label,
        path=path,
        flags=flags,
        driver_path=args.driver_path or browser_config.driver.path,
        viewport=args.viewport,
        splash_screen=args.splash_screen,
        platform=browser_platform)
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


class ProbeConfigError(argparse.ArgumentTypeError):
  pass



PROBE_LOOKUP: Dict[str, Type[Probe]] = {
    cls.NAME: cls for cls in GENERAL_PURPOSE_PROBES
}

_PROBE_CONFIG_RE: Final[re.Pattern] = re.compile(
    r"(?P<probe_name>[\w.]+)(:?(?P<config>\{.*\}))?", re.MULTILINE | re.DOTALL)


@dataclasses.dataclass(frozen=True)
class SingleProbeConfig(ConfigObject):
  cls: Type[Probe]
  config: Dict[str, Any] = dataclasses.field(default_factory=dict)

  @classmethod
  def loads(cls, value: str) -> SingleProbeConfig:
    # 1. variant: known probe
    if value in PROBE_LOOKUP:
      return cls(PROBE_LOOKUP[value])
    # 2. variant: inline hjson
    match = _PROBE_CONFIG_RE.fullmatch(value)
    if match is None:
      raise ProbeConfigError(f"Could not parse probe argument: {value}")
    config = {"name": match["probe_name"]}
    if match["config"]:
      inline_config = parse_inline_hjson(match["config"])
      assert "name" not in inline_config
      config.update(inline_config)
    return cls.load_dict(config)

  @classmethod
  def load_dict(cls,
                config: Dict[str, Any],
                throw: bool = False) -> SingleProbeConfig:
    probe_name = config.pop("name")
    if probe_name not in PROBE_LOOKUP:
      raise ProbeConfigError(f"Unknown probe: '{probe_name}'")
    probe_cls = PROBE_LOOKUP[probe_name]
    return cls(probe_cls, config)

  @property
  def name(self) -> str:
    return self.cls.NAME


class ProbeConfig:

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
               probe_configs: Optional[Iterable[SingleProbeConfig]] = None,
               throw: bool = False):
    self._exceptions = ExceptionAnnotator(throw=throw)
    self._probes: List[Probe] = []
    if not probe_configs:
      return
    for probe_config in probe_configs:
      with self._exceptions.capture(f"Parsing --probe={probe_config.name}"):
        self.add_probe(probe_config)

  @property
  def probes(self) -> List[Probe]:
    self._exceptions.assert_success("Could not load probes: {}",
                                    ConfigFileError)
    return self._probes

  def add_probe(self, probe_config: SingleProbeConfig) -> None:
    probe: Probe = probe_config.cls.from_config(
        probe_config.config, throw=self._exceptions.throw)
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

  def load_dict(self, config: Dict[str, Any]) -> None:
    for probe_name, config_data in config.items():
      with self._exceptions.info(
          f"Parsing probe config probes['{probe_name}']"):
        if probe_name not in PROBE_LOOKUP:
          self.raise_unknown_probe(probe_name)
        probe_cls = PROBE_LOOKUP[probe_name]
        self._probes.append(probe_cls.from_config(config_data))

  def raise_unknown_probe(self, probe_name: str) -> None:
    additional_msg = ""
    if ":" in probe_name or "}" in probe_name:
      additional_msg = "\n    Likely missing quotes for --probe argument"
    msg = f"    Options are: {list(PROBE_LOOKUP.keys())}{additional_msg}"
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
    kwargs = parse_inline_hjson(value)
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
