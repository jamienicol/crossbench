# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
import collections
import inspect
import textwrap
import tabulate

from typing import Any, Callable, Dict, List, Optional, Sequence, Type, TYPE_CHECKING

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.probes

ArgParserType = Callable[[Any], Any]


class _ConfigArg:

  def __init__(self,
               parser: ConfigParser,
               name: str,
               type: Optional[ArgParserType],
               default: Any = None,
               choices: Optional[Sequence[Any]] = None,
               help: Optional[str] = None,
               is_list: bool = False):
    self.parser = parser
    self.name = name
    self.type = type
    self.default = default
    self.choices = choices
    self.help = help
    self.is_list = is_list
    if self.type:
      assert callable(self.type), (
          f"Expected type to be a class or a callable, but got: {self.type}")
    if self.default is not None:
      self._validate_default()

  def _validate_default(self):
    if self.is_list:
      assert isinstance(self.default, collections.abc.Sequence), (
          "List default must be a sequence, but got: {self.default}")
      if inspect.isclass(self.type):
        for default_item in self.default:
          assert isinstance(
              default_item,
              self.type), (f"Expected default list item of type={self.type}, "
                           f"but got type={type(default_item)}: {default_item}")
    elif inspect.isclass(self.type):
      assert isinstance(
          self.default,
          self.type), (f"Expected default value of type={self.type}, "
                       f"but got type={type(self.default)}: {self.default}")

  @property
  def probe_name(self) -> str:
    return self.parser.probe_cls.NAME

  @property
  def help_text(self):
    items: List[str] = []
    if self.help:
      items.append(self.help)
    if self.type is None:
      if self.is_list:
        items.append(f"type = list")
    else:
      if self.is_list:
        items.append(f"type = List[{self.type}]")
      else:
        items.append(f"type = {self.type}")

    if self.default is None:
      items.append("default = not set")
    else:
      if self.is_list:
        items.append(f"default = {','.join(map(str, self.default))}")
      else:
        items.append(f"default = {self.default}")
    if self.choices:
      items.append(f"choices = {', '.join(map(str, self.choices))}")

    return "\n".join(items)

  def parse(self, config_data: Dict[str, Any]):
    data = config_data.pop(self.name, None)
    if data is None:
      if self.default is None:
        raise ValueError(
            f"Probe {self.probe_name}: "
            f"No value provided for required config option '{self.name}'")
      data = self.default
    if self.is_list:
      return self.parse_list_data(data)
    return self.parse_data(data)

  def parse_list_data(self, data: Any) -> List[Any]:
    if not isinstance(data, (list, tuple)):
      raise ValueError(f"Probe {self.probe_name}.{self.name}: "
                       f"Expected sequence got {type(data)}")
    return [self.parse_data(value) for value in data]

  def parse_data(self, data: Any) -> Any:
    if self.type is None:
      return data
    elif self.type is bool:
      if not isinstance(data, bool):
        raise ValueError(f"Expected bool, but got {data}")
    elif self.type in (float, int):
      if not isinstance(data, (float, int)):
        raise ValueError(f"Expected number, got {data}")
    return self.type(data)


class ConfigParser:

  def __init__(self, probe_cls: Type[cb.probes.Probe]):
    self.probe_cls = probe_cls
    self._args: Dict[str, _ConfigArg] = dict()

  def add_argument(self,
                   name: str,
                   type: Optional[ArgParserType],
                   default: Any = None,
                   choices: Optional[Sequence[Any]] = None,
                   help: Optional[str] = None,
                   is_list: bool = False):
    assert name not in self._args, f"Duplicate argument: {name}"
    self._args[name] = _ConfigArg(self, name, type, default, choices, help,
                                  is_list)

  @property
  def doc(self) -> str:
    assert self.probe_cls.__doc__
    return self.probe_cls.__doc__.strip()

  def kwargs_from_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    for arg in self._args.values():
      kwargs[arg.name] = arg.parse(config_data)
    return kwargs

  def __str__(self):
    doc = ["\n".join(textwrap.wrap(self.doc, width=60))]
    if not self._args:
      return doc[0]
    doc.extend(["", "Probe Configuration:", ""])
    for arg in self._args.values():
      doc.append(f"{arg.name}:")
      doc.extend(wrap_lines(arg.help_text, width=58, indent="  "))
      doc.append("")

    return "\n".join(doc)


def wrap_lines(body, width, indent):
  for line in body.splitlines():
    for split in textwrap.wrap(line, width):
      yield f"{indent}{split}"
