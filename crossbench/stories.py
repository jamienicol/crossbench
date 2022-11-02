# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import List, Sequence, TYPE_CHECKING, Tuple, Type, TypeVar

import crossbench as cb
if TYPE_CHECKING:
  import crossbench.probes


class Story(ABC):
  PROBES: Tuple[Type[cb.probes.Probe], ...] = ()

  @classmethod
  @abstractmethod
  def story_names(cls) -> Sequence[str]:
    pass

  def __init__(self, name: str, duration: float = 15):
    assert name, "Invalid page name"
    self._name = name
    assert duration > 0, (
        f"Duration must be a positive number, but got: {duration}")
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


TPressBenchmarkStory = TypeVar(
    "TPressBenchmarkStory", bound="PressBenchmarkStory")


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
  def from_names(cls: Type[TPressBenchmarkStory],
                 substories: Sequence[str],
                 separate: bool = False,
                 live: bool = False) -> List[TPressBenchmarkStory]:
    if live:
      return cls.live(substories=substories, separate=separate)
    return cls.local(substories=substories, separate=separate)

  @classmethod
  def default(cls: Type[TPressBenchmarkStory],
              live: bool = True,
              separate: bool = False):
    if live:
      return cls.live(cls.story_names(), separate)
    return cls.local(cls.story_names(), separate)

  @classmethod
  def local(cls: Type[TPressBenchmarkStory],
            substories: Sequence[str],
            separate: bool = False,
            **kwargs) -> List[TPressBenchmarkStory]:
    if not substories:
      raise ValueError("No substories provided")
    if separate:
      return [
          cls(is_live=False, substories=[substory], **kwargs)  # pytype: disable=not-instantiable
          for substory in substories
      ]
    else:
      return [cls(is_live=False, substories=substories, **kwargs)]  # pytype: disable=not-instantiable


  @classmethod
  def live(cls: Type[TPressBenchmarkStory],
           substories: Sequence[str],
           separate: bool = False,
           **kwargs) -> List[TPressBenchmarkStory]:
    if not substories:
      raise ValueError("No substories provided")
    if separate:
      return [
          cls(is_live=True, substories=[substory], **kwargs)  # pytype: disable=not-instantiable
          for substory in substories
      ]
    else:
      return [cls(is_live=False, substories=substories, **kwargs)]  # pytype: disable=not-instantiable

  _substories: Sequence[str]
  is_live : bool
  _url: str

  def __init__(self,
               *args,
               is_live: bool = True,
               substories: Sequence[str] = (),
               **kwargs):
    cls = self.__class__
    assert self.SUBSTORIES, f"{cls}.SUBSTORIES is not set."
    assert self.NAME is not None, f"{cls}.NAME is not set."
    self._verify_url(self.URL, "URL")
    self._verify_url(self.URL_LOCAL, "URL_LOCAL")
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
