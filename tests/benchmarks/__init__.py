# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import pathlib
import pyfakefs.fake_filesystem_unittest

from .. import mockbenchmark

import crossbench as cb


class BaseBenchmarkTestCase(
    pyfakefs.fake_filesystem_unittest.TestCase, metaclass=abc.ABCMeta):

  @property
  @abc.abstractmethod
  def benchmark_cls(self):
    pass

  @property
  def story_cls(self):
    return self.benchmark_cls.DEFAULT_STORY_CLS

  def setUp(self):
    self.setUpPyfakefs(modules_to_reload=[cb, mockbenchmark])
    self.assertTrue(
        issubclass(self.benchmark_cls, cb.benchmarks.Benchmark),
        f"Expected Benchmark subclass, but got: BENCHMARK={self.benchmark_cls}")
    mockbenchmark.MockChromeDev.setup_fs(self.fs)
    mockbenchmark.MockChromeStable.setup_fs(self.fs)
    self.platform = mockbenchmark.mock_platform
    self.out_dir = pathlib.Path("tmp/results/test")
    self.out_dir.parent.mkdir(parents=True)
    self.browsers = [
        mockbenchmark.MockChromeDev("dev", platform=self.platform),
        mockbenchmark.MockChromeStable("stable", platform=self.platform)
    ]


class BenchmarkTestCaseMixin:

  def test_stories_creation(self):
    for name in self.story_cls.story_names():
      stories = self.story_cls.from_names([name])
      self.assertTrue(len(stories) == 1)
      story = stories[0]
      self.assertIsInstance(story, self.story_cls)
      self.assertIsInstance(story.details_json(), dict)
      self.assertTrue(len(str(story)) > 0)

  def test_instantiate_no_stories(self):
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories=[])
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories="")
    with self.assertRaises(AssertionError):
      self.benchmark_cls(stories=["", ""])

  def test_instantiate_single_story(self):
    any_story_name = self.story_cls.story_names()[0]
    any_story = self.story_cls.from_names([any_story_name])[0]
    # Instantiate with single story,
    self.benchmark_cls(any_story)
    # with single story array
    self.benchmark_cls([any_story])
    with self.assertRaises(AssertionError):
      # Accidentally nested array.
      self.benchmark_cls([[any_story]])

  def test_instantiate_all_stories(self):
    stories = self.story_cls.from_names(self.story_cls.story_names())
    self.benchmark_cls(stories)

  def test_describe(self):
    self.assertIsInstance(self.benchmark_cls.describe(), dict)


class PressBenchmarkTestCaseMixin(BenchmarkTestCaseMixin):

  def test_invalid_story_names(self):
    with self.assertRaises(Exception):
      # Only one regexp entry will work
      self.story_cls.from_names([".*", 'a'], separate=True)