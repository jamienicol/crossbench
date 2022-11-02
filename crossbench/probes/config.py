# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations
import tabulate

from typing import Any, Callable, Dict, List, Optional, Sequence, Type, TYPE_CHECKING

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.probes

ArgParserType = Callable[[Any], Any]


class _ConfigArg:

  def __init__(self,
               parser: ProbeConfigParser,
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
        items.append(f" type = List[{self.type}]")
      else:
        items.append(f" type = {self.type}")
    elif self.is_list:
      items.append(f" type = list")

    if self.default:
      items.append(f"default = {self.default}")
    if self.choices:
      items.append(f"choices = {self.choices}")

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


class ProbeConfigParser:

  def __init__(self, probe_cls: Type[cb.probes.Probe]):
    self.probe_cls = probe_cls
    self._args: Dict[str, _ConfigArg] = dict()

  def add_argument(self,
                   name: str,
                   type: ArgParserType,
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
    if not self._args:
      return self.doc
    help = {arg.name: arg.help_text for arg in self._args.values()}
    config_help = tabulate.tabulate(help.items())
    return f"{self.doc}\n\nConfig:\n{config_help}"
