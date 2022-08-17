# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
from typing import Optional, Iterable, Dict

class Flags(collections.UserDict):
  @classmethod
  def split(cls, flag_str: str):
    if "=" in flag_str:
      return flag_str.split("=", maxsplit=1)
    return (flag_str, None)

  def __init__(self,
               initial_data: Optional[Dict[str, str] | "Flags"
                                      | Iterable[str]] = None):
    super().__init__(initial_data)

  def __setitem__(self, flag_name, flag_value):
    return self.set(flag_name, flag_value)

  def set(self, flag_name: str, flag_value=None, override=False):
    if not override and flag_name in self:
      old_value = self[flag_name]
      assert flag_value == old_value, (
          f"Flag {flag_name}={flag_value} was already set "
          f"with a different previous value: '{old_value}'")
      return
    self._set(flag_name, flag_value, override)

  def _set(self, flag_name: str, flag_value=None, override=False):
    assert len(flag_name) > 0, "Cannot set empty flag"
    assert "=" not in flag_name, (
        f"Flag name contains '=': {flag_name}, please split")
    assert flag_name.startswith("-"), f"Invalid flag name: {flag_name}"
    assert flag_value is None or isinstance(flag_value, str)
    self.data[flag_name] = flag_value

  def update(self,
             initial_data: Optional[Dict[str, str] | "Flags"
                                    | Iterable[str]
                                    | Iterable[tuple[str, str]]] = None,
                                    override=False):
    if initial_data is None:
      return
    if isinstance(initial_data, (Flags, dict)):
      for flag_name, flag_value in initial_data.items():
        self.set(flag_name, flag_value, override)
    else:
      for flag_name_or_items in initial_data:
        if isinstance(flag_name_or_items, str):
          self.set(flag_name_or_items, None, override)
        else:
          flag_name, flag_value = flag_name_or_items
          self.set(flag_name, flag_value, override)

  def copy(self):
    return self.__class__(self)

  def _describe(self, flag_name):
    value = self.get(flag_name)
    if value is None:
      return flag_name
    return f"{flag_name}={value}"

  def get_list(self):
    return (k if v is None else f"{k}={v}" for k, v in self.items())

  def __str__(self):
    return " ".join(self.get_list())


class JSFlags(Flags):
  _NO_PREFIX = "--no"

  def _set(self, flag_name, flag_value=None, override=False):
    if flag_value is not None:
      assert "," not in flag_value, (
          "Comma in flag value, flag escaping for chrome's "
          f"--js-flag might not work: {flag_name}={flag_value}")
    assert flag_name.startswith("--"), (
        f"Only long-form flag names allowed: got '{flag_name}'")
    self._check_negated_flag(flag_name, override)
    super()._set(flag_name, flag_value, override)

  def _check_negated_flag(self, flag_name, override):
    if flag_name.startswith(self._NO_PREFIX):
      enabled = flag_name[len(self._NO_PREFIX):]
      # Check for --no-foo form
      if enabled.startswith('-'):
        enabled = enabled[1:]
      enabled = "--" + enabled
      if override:
        del self[enabled]
      else:
        assert not enabled in self, (
            f"Conflicting flag '{flag_name}', "
            f"it has already been enabled by '{self._describe(enabled)}'")
    else:
      # --foo => --no-foo
      disabled = f"--no-{flag_name[2:]}"
      if not disabled in self:
        # Try compact version: --foo => --nofoo
        disabled = f"--no{flag_name[2:]}"
        if not disabled in self:
          return
      if override:
        del self[disabled]
      else:
        assert False, (
            f"Conflicting flag '{flag_name}', "
            f"it has previously been disabled by '{self._describe(flag_name)}")

  def __str__(self):
    return ",".join(self.get_list())


class ChromeFlags(Flags):
  _JS_FLAG = "--js-flags"

  def __init__(self, initial_data=None):
    self._features = ChromeFeatures()
    self._js_flags = JSFlags()
    super().__init__(initial_data)

  def _set(self, flag_name, flag_value, override=False):
    if flag_name == ChromeFeatures._ENABLE_FLAG:
      for feature in flag_value.split(","):
        self._features.enable(feature)
    elif flag_name == ChromeFeatures._DISABLE_FLAG:
      for feature in flag_value.split(","):
        self._features.disable(feature)
    elif flag_name == self._JS_FLAG:
      new_js_flags = JSFlags(self._js_flags)
      for js_flag in flag_value.split(","):
        js_flag_name, js_flag_value = Flags.split(js_flag.lstrip())
        new_js_flags.set(js_flag_name, js_flag_value, override=override)
      self._js_flags.update(new_js_flags)
    else:
      return super()._set(flag_name, flag_value, override)

  @property
  def features(self):
    return self._features

  @property
  def js_flags(self):
    return self._js_flags

  def get_list(self):
    yield from super().get_list()
    if len(self._js_flags):
      yield f"{self._JS_FLAG}={self._js_flags}"
    if not self._features.is_empty:
      yield from self._features.get_list()


class ChromeFeatures:
  _ENABLE_FLAG = "--enable-features"
  _DISABLE_FLAG = "--disable-features"
  """
  Chrome Features set, throws if features are enabled and disabled at the same
  time.
  Examples:
    --disable-features="MyFeature1"
    --enable-features="MyFeature1,MyFeature2"
    --enable-features="MyFeature1:k1/v1/k2/v2,MyFeature2"
    --enable-features="MyFeature3<Trial2:k1/v1/k2/v2"
  """

  def __init__(self):
    self._enabled = {}
    self._disabled = set()

  @property
  def is_empty(self):
    return len(self._enabled) == 0 and len(self._disabled) == 0

  @property
  def enabled(self):
    return self._enabled

  @property
  def disabled(self):
    return self._disabled

  def _parse_feature(self, feature: str):
    assert feature, "Cannot parse empty feature"
    assert "," not in feature, \
        f"'{feature}' contains multiple features. Please split them first."
    parts = feature.split("<")
    if len(parts) == 2:
      return (parts[0], '<' + parts[1])
    assert len(parts) == 1
    parts = feature.split(":")
    if len(parts) == 2:
      return (parts[0], ':' + parts[1])
    assert len(parts) == 1
    return (feature, None)

  def enable(self, feature):
    name, value = self._parse_feature(feature)
    assert name not in self._disabled, \
        f"Cannot enable previously disabled feature={name}"
    if name in self._enabled:
      prev_value = self._enabled[name]
      assert value == prev_value, (
          f"Cannot set conflicting values ('{prev_value}', vs. '{value}') "
          f"for the same feature={name}")
    else:
      self._enabled[name] = value

  def disable(self, feature):
    name, _ = self._parse_feature(feature)
    assert name not in self._enabled, \
        f"Cannot disable previously enabled feature={name}"
    self._disabled.add(name)

  def get_list(self):
    if len(self._enabled) > 0:
      joined = ",".join(k if v is None else f"{k}{v}"
                        for k, v in self._enabled.items())
      yield f"{self._ENABLE_FLAG}={joined}"
    if len(self._disabled) > 0:
      joined = ",".join(self._disabled)
      yield f"{self._DISABLE_FLAG}={joined}"

  def __str__(self):
    result = " ".join(self.get_list())
    return result
