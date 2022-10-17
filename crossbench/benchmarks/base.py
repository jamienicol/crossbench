# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import Iterable, Sequence, TYPE_CHECKING, Type, Union
import argparse

if TYPE_CHECKING:
  import crossbench as cb
import crossbench.stories as cb_stories


class Benchmark(abc.ABC):
  NAME: str = ""
  DEFAULT_STORY_CLS: Type[cb_stories.Story] = cb_stories.Story

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    assert cls.__doc__ and cls.__doc__, (
    f"Benchmark class {cls} must provide a doc string.")
    doc_title = cls.__doc__.strip().split("\n")[0]
    parser = subparsers.add_parser(
        cls.NAME,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help=doc_title,
        description=cls.__doc__.strip())
    return parser

  @classmethod
  def describe(cls):
    return {
        "name": cls.NAME,
        "description": cls.__doc__.strip(),
        "stories": [],
        "probes-default": {
            probe_cls.NAME: probe_cls.__doc__.strip()
            for probe_cls in cls.DEFAULT_STORY_CLS.PROBES
        }
    }

  def __init__(self,
               stories: Union[cb_stories.Story, Sequence[cb_stories.Story]]):
    assert self.NAME is not None, f"{self} has no .NAME property"
    assert self.DEFAULT_STORY_CLS != cb_stories.Story, (
        f"{self} has no .DEFAULT_STORY_CLS property")
    if isinstance(stories, cb_stories.Story):
      stories = [stories]
    self.stories: Sequence[cb_stories.Story] = stories
    self._validate_stories()

  def _validate_stories(self):
    assert self.stories, "No stories provided"
    for story in self.stories:
      assert isinstance(story, self.DEFAULT_STORY_CLS), (
          f"story={story} has not the same class as {self.DEFAULT_STORY_CLS}")
    first_story = self.stories[0]
    expected_probes_cls_list = first_story.PROBES
    for story in self.stories:
      assert story.PROBES == expected_probes_cls_list, (
          f"story={story} has different PROBES than {first_story}")


class SubStoryBenchmark(Benchmark):

  @classmethod
  def parse_cli_stories(cls, values):
    return tuple(story.strip() for story in values.split(","))

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers)
    parser.add_argument(
        "--stories",
        default="all",
        type=cls.parse_cli_stories,
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
  def kwargs_from_cli(cls, args) -> dict:
    return dict(stories=cls.stories_from_cli(args))

  @classmethod
  def stories_from_cli(cls, args) -> Iterable[cb_stories.Story]:
    assert issubclass(cls.DEFAULT_STORY_CLS, cb_stories.Story), (
        f"{cls.__name__}.DEFAULT_STORY_CLS is not a Story class. "
        f"Got '{cls.DEFAULT_STORY_CLS}' instead.")
    return cls.DEFAULT_STORY_CLS.from_names(args.stories, args.separate)

  @classmethod
  def describe(cls) -> dict:
    data = super().describe()
    data["stories"] = cls.story_names()
    return data

  @classmethod
  def story_names(cls) -> Iterable[str]:
    return cls.DEFAULT_STORY_CLS.story_names()


class PressBenchmark(SubStoryBenchmark):

  @classmethod
  def add_cli_parser(cls, subparsers) -> argparse.ArgumentParser:
    parser = super().add_cli_parser(subparsers)
    is_live_group = parser.add_mutually_exclusive_group()
    is_live_group.add_argument(
        "--live",
        default=True,
        action="store_true",
        help="Use live/online benchmark url.")
    is_live_group.add_argument(
        "--local",
        dest="live",
        action="store_false",
        help="Use locally hosted benchmark url.")
    return parser

  @classmethod
  def stories_from_cli(cls, args) -> Iterable[cb_stories.PressBenchmarkStory]:
    assert issubclass(cls.DEFAULT_STORY_CLS, cb_stories.PressBenchmarkStory)
    return cls.DEFAULT_STORY_CLS.from_names(args.stories, args.separate,
                                            args.live)

  @classmethod
  def describe(cls) -> dict:
    data = super().describe()
    assert issubclass(cls.DEFAULT_STORY_CLS, cb_stories.PressBenchmarkStory)
    data["url"] = cls.DEFAULT_STORY_CLS.URL
    data["url-local"] = cls.DEFAULT_STORY_CLS.URL_LOCAL
    return data
