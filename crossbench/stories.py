# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import re
from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Type, Union

if TYPE_CHECKING:
  import crossbench as cb


class Story(ABC):
  PROBES: Tuple[Type[cb.probes.Probe], ...] = ()

  @classmethod
  @abstractmethod
  def story_names(cls) -> Sequence[str]:
    pass

  @classmethod
  @abstractmethod
  def from_names(cls, names, separate=False) -> Sequence[Story]:
    pass

  @classmethod
  def from_cli_args(cls, args) -> Sequence[Story]:
    # TODO: make this more uniform with other args-parsing APIs
    return cls.from_names(args.stories, args.separate)

  def __init__(self, name: str, duration: float = 15):
    assert name, "Invalid page name"
    self._name = name
    assert duration > 0, (
        f"duration must be a positive number, but got: {duration}")
    self.duration = duration

  @property
  def name(self) -> str:
    return self._name

  def details_json(self):
    return {"name": self.name, "duration": self.duration}

  def is_done(self, _) -> bool:
    return True

  @abstractmethod
  def run(self, run):
    pass

  def __str__(self):
    return f"Story(name={self.name})"


class PressBenchmarkStory(Story, metaclass=ABCMeta):
  NAME: str = ""
  URL: str = ""
  URL_LOCAL: str = ""
  SUBSTORIES: Tuple[str, ...] = ()

  @classmethod
  def story_names(cls) -> Tuple[str, ...]:
    assert cls.SUBSTORIES
    return cls.SUBSTORIES

  @classmethod
  def from_names(cls, names:Union[Sequence[str], str], separate=False, live=True):
    if len(names) == 1 or isinstance(names, str):
      if isinstance(names, str):
        first = names
      else:
        first = names[0]
      if first == "all":
        names = cls.story_names()
      elif first not in cls.story_names():
        pattern = re.compile(first)
        names = tuple(substory for substory in cls.story_names()
                      if pattern.match(substory))
        assert names, (
            f"Regexp '{pattern.pattern}' didn't match any cb.stories")
        logging.info("FILTERED SUB-STORIES story=%s selected=%s", cls.NAME,
                     names)
    if live:
      return cls.live(separate=separate, substories=names)
    return cls.local(separate=separate, substories=names)

  @classmethod
  def default(cls):
    return cls.live()

  @classmethod
  def local(cls, *args, separate=False, substories=None, **kwargs):
    substories = cls.get_substories(separate, substories)
    return [
        cls(*args, is_live=False, benchmarks=substory, **kwargs)
        for substory in substories
    ]

  @classmethod
  def live(cls, *args, separate=False, substories=None, **kwarg):
    substories = cls.get_substories(separate, substories)
    return [
        cls(*args, is_live=True, substories=substory, **kwarg)
        for substory in substories
    ]

  @classmethod
  def get_substories(cls, separate:bool, substories:Sequence[str]):
    substories = substories or cls.story_names()
    if separate:
      return substories
    return [substories]


  _substories: Sequence[str]
  is_live : bool
  _url: str

  def __init__(self,
               *args,
               is_live: bool = True,
               substories: Optional[Union[str, List[str]]] = None,
               **kwargs):
    cls = self.__class__
    assert self.SUBSTORIES, f"{cls}.SUBSTORIES is not set."
    assert self.NAME is not None, f"{cls}.NAME is not set."
    self._verify_url(self.URL, "URL")
    self._verify_url(self.URL_LOCAL, "URL_LOCAL")
    if isinstance(substories, str):
      self._substories = [substories]
    else:
      self._substories = substories or self.story_names()
    self._verify_substories()
    name = self.NAME
    if self._substories != self.story_names():
      name += "_" + ("_".join(self._substories))
    kwargs["name"] = name
    super().__init__(*args, **kwargs)
    self.is_live = is_live
    if is_live:
      self._url = self.URL
    else:
      self._url = self.URL_LOCAL
    assert self._url is not None, f"Invalid URL for {self.NAME}"

  def _verify_url(self, url:str, property_name:str):
    cls = self.__class__
    assert url is not None, f"{cls}.{property_name} is not set."

  def _verify_substories(self):
    if len(self._substories) != len(set(self._substories)):
      # Beware of the O(n**2):
      duplicates = set(
          substory for substory in self._substories
          if self._substories.count(substory) > 1)
      assert duplicates, (
          f"substories='{self._substories}' contains duplicate entries: "
          f"{duplicates}")
    if self._substories == self.SUBSTORIES:
      return
    for substory in self._substories:
      assert substory in self.SUBSTORIES, (f"Unknown {self.NAME} substory %s" %
                                           substory)
