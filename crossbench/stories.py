# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
import abc
from typing import List, Optional, Sequence, TYPE_CHECKING, Tuple, Type, TypeVar

if TYPE_CHECKING:
  from crossbench.probes import Probe


class Story(ABC):
  PROBES: Tuple[Type[Probe], ...] = ()

  @classmethod
  @abstractmethod
  def all_story_names(cls) -> Sequence[str]:
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


PressBenchmarkStoryT = TypeVar(
    "PressBenchmarkStoryT", bound="PressBenchmarkStory")


class PressBenchmarkStory(Story, metaclass=ABCMeta):
  NAME: str = ""
  URL: str = ""
  URL_LOCAL: str = ""
  SUBSTORIES: Tuple[str, ...] = ()

  @classmethod
  def all_story_names(cls) -> Tuple[str, ...]:
    assert cls.SUBSTORIES
    return cls.SUBSTORIES

  @classmethod
  def default_story_names(cls) -> Tuple[str, ...]:
    """Override this method to use a subset of all_story_names as default
    selection if no story names are provided."""
    return cls.all_story_names()

  @classmethod
  def from_names(cls: Type[PressBenchmarkStoryT],
                 substories: Sequence[str],
                 separate: bool = False,
                 is_live: bool = False) -> List[PressBenchmarkStoryT]:
    if is_live:
      return cls.live(substories=substories, separate=separate)
    return cls.local(substories=substories, separate=separate)

  @classmethod
  def all(cls: Type[PressBenchmarkStoryT],
          is_live: bool = True,
          separate: bool = False):
    if is_live:
      return cls.live(cls.all_story_names(), separate)
    return cls.local(cls.all_story_names(), separate)

  @classmethod
  def default(cls: Type[PressBenchmarkStoryT],
              is_live: bool = True,
              separate: bool = False):
    if is_live:
      return cls.live(cls.default_story_names(), separate)
    return cls.local(cls.default_story_names(), separate)

  @classmethod
  def local(cls: Type[PressBenchmarkStoryT],
            substories: Sequence[str],
            separate: bool = False,
            **kwargs) -> List[PressBenchmarkStoryT]:
    if not substories:
      raise ValueError("No substories provided")
    if separate:
      return [
          cls(  # pytype: disable=not-instantiable
              is_live=False,
              substories=[substory],
              **kwargs) for substory in substories
      ]
    return [
        cls(  # pytype: disable=not-instantiable
            is_live=False,
            substories=substories,
            **kwargs)
    ]


  @classmethod
  def live(cls: Type[PressBenchmarkStoryT],
           substories: Sequence[str],
           separate: bool = False,
           **kwargs) -> List[PressBenchmarkStoryT]:
    if not substories:
      raise ValueError("No substories provided")
    if separate:
      return [
          cls(  # pytype: disable=not-instantiable
              is_live=True,
              substories=[substory],
              **kwargs) for substory in substories
      ]
    return [
        cls(  # pytype: disable=not-instantiable
            is_live=True,
            substories=substories,
            **kwargs)
    ]

  _substories: Sequence[str]
  is_live : bool
  _url: str

  def __init__(self,
               *args,
               is_live: bool = True,
               substories: Sequence[str] = (),
               duration: Optional[float] = None,
               **kwargs):
    cls = self.__class__
    assert self.SUBSTORIES, f"{cls}.SUBSTORIES is not set."
    assert self.NAME is not None, f"{cls}.NAME is not set."
    self._verify_url(self.URL, "URL")
    self._verify_url(self.URL_LOCAL, "URL_LOCAL")
    assert substories, f"No substories provided for {cls}"
    self._substories = substories
    self._verify_substories()
    kwargs["name"] = self._get_unique_name()
    kwargs["duration"] = duration or self._get_initial_duration()
    super().__init__(*args, **kwargs)
    self.is_live = is_live
    if is_live:
      self._url = self.URL
    else:
      self._url = self.URL_LOCAL
    assert self._url is not None, f"Invalid URL for {self.NAME}"

  def _get_unique_name(self) -> str:
    substories_set = set(self._substories)
    if substories_set == set(self.default_story_names()):
      return self.NAME
    if substories_set == set(self.all_story_names()):
      name = f"{self.NAME}_all"
    else:
      name = f"{self.NAME}_" + ("_".join(self._substories))
    if len(name) > 220:
      # Crop the name and add some random hash bits
      name = name[:220] + hex(hash(name))[2:10]
    return name

  def _get_initial_duration(self) -> float:
    # Fixed delay for startup costs
    startup_delay = 2
    # Add some slack due to different story lengths
    story_factor = 0.5 + 1.1 * len(self._substories)
    return startup_delay + story_factor * self.substory_duration

  @property
  def fast_duration(self) -> float:
    """Expected benchmark duration on fast machines.
    Keep this low enough to not have to wait needlessly at the end of a
    benchmark.
    """
    return self.duration / 2

  @property
  def slow_duration(self) -> float:
    """Max duration that covers run-times on slow machines and/or
    debug-mode browsers.
    Making this number too large might cause needless wait times on broken
    browsers/benchmarks.
    """
    return 15 + self.duration * 4

  @property
  @abc.abstractmethod
  def substory_duration(self) -> float:
    pass

  @property
  def url(self):
    return self._url

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
