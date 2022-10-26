# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from __future__ import annotations

import abc
import re
from typing import Iterable, Optional, Sequence, TYPE_CHECKING, Type
from urllib.parse import urlparse

if TYPE_CHECKING:
  import crossbench as cb

import crossbench.stories as cb_stories
import crossbench.benchmarks.base as benchmarks


class Page(cb_stories.Story, metaclass=abc.ABCMeta):
  @classmethod
  def story_names(cls):
    return tuple(page.name for page in PAGE_LIST)

class LivePage(Page):

  def __init__(self, name, url, duration=15):
    super().__init__(name, duration)
    assert url, "Invalid page url"
    self.url = url

  def details_json(self):
    result = super().details_json()
    result["url"] = str(self.url)
    return result

  def run(self, run):
    run.browser.show_url(run.runner, self.url)
    run.runner.wait(self.duration + 1)

  def __str__(self):
    return f"Page(name={self.name}, url={self.url})"


class CombinedPage(Page):

  def __init__(self, pages: Sequence[Page], name="combined"):
    assert len(pages), "No sub-pages provided for CombinedPage"
    assert len(pages) > 1, "Combined Page needs more than one page"
    self._pages = pages
    duration = sum(page.duration for page in pages)
    super().__init__(name, duration)
    self.url = None

  def details_json(self):
    result = super().details_json()
    result["pages"] = list(page.details_json() for page in self._pages)
    return result

  def run(self, run):
    for page in self._pages:
      page.run(run)

  def __str__(self):
    combined_name = ",".join(page.name for page in self._pages)
    return f"CombinedPage({combined_name})"


PAGE_LIST = [
    LivePage("amazon", "https://www.amazon.de/s?k=heizkissen", 5),
    LivePage("bing", "https://www.bing.com/images/search?q=not+a+squirrel", 5),
    LivePage("caf", "http://www.caf.fr", 6),
    LivePage("cnn", "https://cnn.com/", 7),
    LivePage("ecma262", "https://tc39.es/ecma262/#sec-numbers-and-dates", 10),
    LivePage("expedia", "https://www.expedia.com/", 7),
    LivePage("facebook", "https://facebook.com/shakira", 8),
    LivePage("maps", "https://goo.gl/maps/TEZde4y4Hc6r2oNN8", 10),
    LivePage("microsoft", "https://microsoft.com/", 6),
    LivePage("provincial", "http://www.provincial.com", 6),
    LivePage("sueddeutsche", "https://www.sueddeutsche.de/wirtschaft", 8),
    LivePage("timesofindia", "https://timesofindia.indiatimes.com/", 8),
    LivePage("twitter", "https://twitter.com/wernertwertzog?lang=en", 6),
]
PAGES = {page.name: page for page in PAGE_LIST}


class LoadingPageFilter(benchmarks.StoryFilter):
  """
  Filter / create loading stories

  Syntax:
    "name"            Include LivePage with the given name from predefined list.
    "name", 10        Include predefined page with given 10s timeout.
    "http://..."      Include custom page at the given URL with a default
                      timout of 15 seconds.
    "http://...", 12  Include custom page at the given URL with a 12s timout

  These patterns can be combined:
    ["http://foo.com", 5, "http://bar.co.jp", "amazon"]
  """
  _DURATION_RE = re.compile(r"((\d*[.])?\d+)s?")

  @classmethod
  def kwargs_from_cli(self, args):
    kwargs = super().kwargs_from_cli(args)
    kwargs["separate"] = args.separate
    return kwargs

  def __init__(self,
               story_cls: Type[Page],
               names: Sequence[str],
               separate: bool = True):
    self.separate = separate
    super().__init__(story_cls, names)

  def process_all(self, name_or_url_list: Sequence[str]):
    if len(name_or_url_list) == 1 and name_or_url_list[0] == "all":
      self.stories = PAGE_LIST
      return
    self._resolve_name_or_urls(name_or_url_list)
    # Check if we have unique domain names for better short names
    urls = list(urlparse(page.url) for page in self.stories)
    hostnames = set(url.hostname for url in urls)
    if len(hostnames) == len(urls):
      # Regenerate with short names
      self._resolve_name_or_urls(name_or_url_list, use_hostname=True)

  def _resolve_name_or_urls(self, name_or_url_list, use_hostname=False):
    page = None
    self.stories = []
    for value in name_or_url_list:
      if value in PAGES:
        page = PAGES[value]
      elif "://" in value:
        name = value
        url = value
        if use_hostname:
          name = urlparse(url).hostname
        page = LivePage(name, url)
      else:
        # Use the last created page and set the duration on it
        assert page is not None, (
            f"Duration '{value}' has to follow a URL or page-name.")
        match = self._DURATION_RE.match(value)
        assert match, f"Duration '{value}' is not a number."
        duration = float(match.group(1))
        assert duration != 0, ("Duration should be positive. "
                               f"Got duration=0 page={page.name}")
        page.duration = duration
        continue
      self.stories.append(page)

  def create_stories(self) -> Iterable[Page]:
    if not self.separate and len(self.stories) > 1:
      combined_name = "_".join(page.name for page in self.stories)
      self.stories = (CombinedPage(self.stories, combined_name),)
    return self.stories


class PageLoadBenchmark(benchmarks.SubStoryBenchmark):
  """
  Benchmark runner for loading pages.

  Use --urls/--stories to either choose from an existing set of pages, or direct
  URLs. After each page you can also specify a custom wait/load duration in
  seconds. Multiple URLs/page names can be provided as a comma-separated list.

  Use --separate to load each page individually.

  Example:
    --urls=amazon
    --urls=http://cnn.com,10s
    --urls=http://twitter.com,5s,http://cnn.com,10s
  """
  NAME = "loading"
  DEFAULT_STORY_CLS = Page
  STORY_FILTER_CLS = LoadingPageFilter

  @classmethod
  def add_cli_parser(cls, subparsers):
    parser = super().add_cli_parser(subparsers)
    parser.add_argument(
        "--urls",
        dest="stories",
        help="List of urls and durations to load: url,seconds,...")
    return parser

  def __init__(self, stories: Sequence[Page], duration: Optional[float] = None):
    for story in stories:
      assert isinstance(story, Page)
      if duration is not None:
        assert duration > 0, f"Invalid page duration={duration}s"
        story.duration = duration
    super().__init__(stories)
