# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
import re
from typing import Any, Dict, Iterable, List, Sequence, Type, cast
import argparse
import logging
import urllib.request

import crossbench as cb
import crossbench.stories

from typing import TypeVar, Generic


class Benchmark(abc.ABC):
  NAME: str = ""
  DEFAULT_STORY_CLS: Type[cb.stories.Story] = cb.stories.Story

  @classmethod
  def add_cli_parser(cls, subparsers,
                     aliases: Sequence[str] = ()) -> argparse.ArgumentParser:
    assert cls.__doc__ and cls.__doc__, (
    f"Benchmark class {cls} must provide a doc string.")
    doc_title = cls.__doc__.strip().split("\n")[0]
    parser = subparsers.add_parser(
        cls.NAME,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help=doc_title,
        description=cls.__doc__.strip(),
        aliases=aliases)
    return parser

  @classmethod
  def describe(cls) -> Dict[str, Any]:
    return {
        "name": cls.NAME,
        "description": cls.__doc__.strip(),
        "stories": [],
        "probes-default": {
            probe_cls.NAME: probe_cls.__doc__.strip()
            for probe_cls in cls.DEFAULT_STORY_CLS.PROBES
        }
    }

  @classmethod
  def kwargs_from_cli(cls, args) -> dict:
    return {}

  @classmethod
  def from_cli_args(cls, args) -> Benchmark:
    kwargs = cls.kwargs_from_cli(args)
    return cls(**kwargs)

  def __init__(self, stories: Sequence[cb.stories.Story]):
    assert self.NAME is not None, f"{self} has no .NAME property"
    assert self.DEFAULT_STORY_CLS != cb.stories.Story, (
        f"{self} has no .DEFAULT_STORY_CLS property")
    self.stories: List[cb.stories.Story] = self._validate_stories(stories)

  def _validate_stories(self, stories: Sequence[cb.stories.Story]
                       ) -> List[cb.stories.Story]:
    assert stories, "No stories provided"
    for story in stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS), (
          f"story={story} should be a subclass/the same "
          f"class as {self.DEFAULT_STORY_CLS}")
    first_story = stories[0]
    expected_probes_cls_list = first_story.PROBES
    for story in stories:
      assert story.PROBES == expected_probes_cls_list, (
          f"story={story} has different PROBES than {first_story}")
    return list(stories)

  def setup(self):
    pass


StoryT = TypeVar("StoryT", bound=cb.stories.Story)


class StoryFilter(Generic[StoryT], metaclass=abc.ABCMeta):

  @classmethod
  def kwargs_from_cli(self, args) -> Dict[str, Any]:
    return {"names": args.stories.split(",")}

  @classmethod
  def from_cli_args(cls, story_cls: Type[StoryT], args):
    kwargs = cls.kwargs_from_cli(args)
    return cls(story_cls, **kwargs)

  def __init__(self, story_cls: Type[StoryT], names: Sequence[str]):
    self.story_cls = story_cls
    assert issubclass(story_cls, cb.stories.Story), (
        f"Subclass of {cb.stories.Story} expected, found {story_cls}")
    # Using order-preserving dict instead of set
    self._known_names: Dict[str, None] = dict.fromkeys(story_cls.story_names())
    self.stories: Sequence[StoryT] = []
    self.process_all(names)
    self.stories = self.create_stories()
    logging.info("STORIES: %s", list(map(str, self.stories)))

  @abc.abstractmethod
  def process_all(self, names: Sequence[str]):
    pass

  @abc.abstractmethod
  def create_stories(self) -> Sequence[StoryT]:
    pass


class SubStoryBenchmark(Benchmark, metaclass=abc.ABCMeta):
  STORY_FILTER_CLS: Type[StoryFilter] = StoryFilter

  @classmethod
  def add_cli_parser(cls, subparsers,
                     aliases: Sequence[str] = ()) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers, aliases)
    parser.add_argument(
        "--stories",
        default="all",
        help="Comma-separated list of story names. Use 'all' as placeholder.")
    is_combined_group = parser.add_mutually_exclusive_group()
    is_combined_group.add_argument(
        "--combined",
        dest="separate",
        default=False,
        action="store_false",
        help="Run each story in the same session. (default)")
    is_combined_group.add_argument(
        "--separate",
        action="store_true",
        help="Run each story in a fresh browser.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args) -> Dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["stories"] = cls.stories_from_cli_args(args)
    return kwargs

  @classmethod
  def stories_from_cli_args(cls, args) -> Sequence[cb.stories.Story]:
    return cls.STORY_FILTER_CLS.from_cli_args(cls.DEFAULT_STORY_CLS,
                                              args).stories

  @classmethod
  def describe(cls) -> Dict[str, Any]:
    data = super().describe()
    data["stories"] = cls.story_names()
    return data

  @classmethod
  def story_names(cls) -> Iterable[str]:
    return cls.DEFAULT_STORY_CLS.story_names()


class PressBenchmarkStoryFilter(StoryFilter[cb.stories.PressBenchmarkStory]):
  """
  Filter stories by name or regexp.

  Syntax:
    "all"     Include all stories (defaults to story_names).
    "name"    Include story with the given name.
    "-name"   Exclude story with the given name'
    "foo.*"   Include stories whose name matches the regexp.
    "-foo.*"  Exclude stories whose name matches the regexp.

  These patterns can be combined:
    [".*", "-foo", "-bar"] Includes allx except the "foo" and "bar" story
  """

  @classmethod
  def kwargs_from_cli(self, args):
    kwargs = super().kwargs_from_cli(args)
    kwargs["separate"] = args.separate
    kwargs["is_live"] = args.is_live
    return kwargs

  def __init__(self,
               story_cls: Type[cb.stories.PressBenchmarkStory],
               names: Sequence[str],
               separate: bool = False,
               is_live: bool = False):
    self.separate = separate
    self.is_live: bool = is_live
    # Using dict instead as ordered set
    self._filtered_names: Dict[str, None] = dict()
    super().__init__(story_cls, names)
    assert issubclass(self.story_cls, cb.stories.PressBenchmarkStory)
    for name in self._known_names:
      assert name, "Invalid empty story name"
      assert not name.startswith("-"), (
          f"Known story names cannot start with '-', but got {name}.")
      assert not name == "all", "Known story name cannot match 'all'."

  def process_all(self, patterns: Sequence[str]):
    if not isinstance(patterns, (list, tuple)):
      raise ValueError("Expected Sequence of story name or patterns "
                       f"but got '{type(patterns)}'.")
    for pattern in patterns:
      self.process_pattern(pattern)

  def process_pattern(self, pattern: str):
    if pattern.startswith("-"):
      self.remove(pattern[1:])
    else:
      self.add(pattern)

  def add(self, pattern: str):
    self._check_processed_pattern(pattern)
    regexp = self._pattern_to_regexp(pattern)
    self._add_matching(regexp, pattern)

  def remove(self, pattern: str):
    self._check_processed_pattern(pattern)
    regexp = self._pattern_to_regexp(pattern)
    self._remove_matching(regexp, pattern)

  def _pattern_to_regexp(self, pattern) -> re.Pattern:
    if pattern == "all":
      return re.compile(".*")
    elif pattern in self._known_names:
      return re.compile(re.escape(pattern))
    return re.compile(pattern)

  def _check_processed_pattern(self, pattern: str):
    if not pattern:
      raise ValueError("Empty pattern is not allowed")
    if pattern == "-":
      raise ValueError(f"Empty remove pattern not allowed: '{pattern}'")
    if pattern[0] == "-":
      raise ValueError(f"Unprocessed negative pattern not allowed: '{pattern}'")

  def _add_matching(self, regexp: re.Pattern, original_pattern: str):
    substories = self._regexp_match(regexp, original_pattern)
    self._filtered_names.update(dict.fromkeys(substories))

  def _remove_matching(self, regexp: re.Pattern, original_pattern: str):
    substories = self._regexp_match(regexp, original_pattern)
    for substory in substories:
      try:
        del self._filtered_names[substory]
      except KeyError as e:
        raise ValueError(
            "Removing Story failed: "
            f"name='{substory}' extracted by pattern='{original_pattern}'"
            "is not in the filtered story list") from e

  def _regexp_match(self, regexp: re.Pattern,
                    original_pattern: str) -> List[str]:
    substories = [
        substory for substory in self._known_names if regexp.fullmatch(substory)
    ]
    if not substories:
      raise ValueError(f"'{original_pattern}' didn't match any stories.")
    logging.info("FILTERED SUB-STORIES story=%s selected=%s",
                 self.story_cls.NAME, substories)
    if len(substories) == len(self._known_names) and self._filtered_names:
      raise ValueError(f"'{original_pattern}' matched all and overrode all"
                       "previously filtered story names.")
    return substories

  def create_stories(self) -> Sequence[StoryT]:
    names = list(self._filtered_names.keys())
    return self.story_cls.from_names(
        names, separate=self.separate, is_live=self.is_live)


class PressBenchmark(SubStoryBenchmark):
  STORY_FILTER_CLS = PressBenchmarkStoryFilter

  @classmethod
  def add_cli_parser(cls, subparsers,
                     aliases: Sequence[str] = ()) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers, aliases)
    is_live_group = parser.add_mutually_exclusive_group()
    is_live_group.add_argument(
        "--live",
        default=True,
        dest="is_live",
        action="store_true",
        help="Use live/online benchmark url.")
    is_live_group.add_argument(
        "--local",
        dest="is_live",
        action="store_false",
        help="Use locally hosted benchmark url.")
    return parser

  @classmethod
  def kwargs_from_cli(cls, args) -> Dict[str, Any]:
    kwargs = super().kwargs_from_cli(args)
    kwargs["is_live"] = args.is_live
    return kwargs

  @classmethod
  def describe(cls) -> dict:
    data = super().describe()
    assert issubclass(cls.DEFAULT_STORY_CLS, cb.stories.PressBenchmarkStory)
    data["url"] = cls.DEFAULT_STORY_CLS.URL
    data["url-local"] = cls.DEFAULT_STORY_CLS.URL_LOCAL
    return data

  def __init__(self, stories: Sequence[cb.stories.Story], is_live: bool = True):
    super().__init__(stories)
    self.is_live: bool = is_live

  def setup(self):
    super().setup()
    self.validate_url()

  def validate_url(self):
    first_story = cast(cb.stories.PressBenchmarkStory, self.stories[0])
    url = first_story.url
    try:
      code = urllib.request.urlopen(url).getcode()
      if code == 200:
        return
    except urllib.error.URLError:
      pass
    message = f"Could not reach benchmark URL: {url}"
    if self.is_live:
      raise Exception(f"Could not reach live benchmark URL: '{url}'. "
                      f"Please make sure you're connected to the internet.")
    raise Exception(f"Could not reach local benchmark URL: '{url}'. "
                    f"Please make sure your local webserver is running")
