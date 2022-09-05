# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
from abc import ABCMeta
from urllib.parse import urlparse

from crossbench import runner, stories


class _Page(stories.Story, metaclass=ABCMeta):
  pass


class LivePage(_Page):
  _DURATION_RE = re.compile(r"((\d*[.])?\d+)s?")

  @classmethod
  def story_names(cls):
    return tuple(page.name for page in PAGE_LIST)

  @classmethod
  def from_names(cls, name_or_url_list, separate=True):
    if len(name_or_url_list) == 1 and name_or_url_list[0] == "all":
      pages = PAGE_LIST
    else:
      pages = cls._resolve_name_or_urls(name_or_url_list)
      # Check if we have unique domain names for better short names
      urls = list(urlparse(page.url) for page in pages)
      hostnames = set(url.hostname for url in urls)
      if len(hostnames) == len(urls):
        pages = cls._resolve_name_or_urls(name_or_url_list, use_hostname=True)
    if not separate and len(pages) > 1:
      combined_name = "_".join(page.name for page in pages)
      pages = (CombinedPage(pages, combined_name),)
    logging.info("PAGES: %s", list(map(str, pages)))
    return pages

  @classmethod
  def _resolve_name_or_urls(cls, name_or_url_list, use_hostname=False):
    pages = []
    page = None
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
        assert page is not None, \
            f"Duration '{value}' has to come follow a URL or page-name."
        match = cls._DURATION_RE.match(value)
        assert match, f"Duration '{value}' is not a number."
        duration = float(match.group(1))
        assert duration > 0, ("Duration should be positive. "
                              f"Got duration={duration} page={page.name}")
        page.duration = duration
        continue
      pages.append(page)
    return pages

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


class CombinedPage(_Page):

  @classmethod
  def story_names(cls):
    raise NotImplementedError()

  @classmethod
  def from_names(cls, names, separate=False):
    raise NotImplementedError()

  def __init__(self, pages, name="combined"):
    assert len(pages), "No sub-pages provided for CombinedPage"
    assert len(pages) > 1, "Combined Page needs more than one page"
    self._pages = pages
    duration = sum(page.duration for page in pages)
    super().__init__(name, duration)

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


class PageLoadRunner(runner.SubStoryRunner):
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
  DEFAULT_STORY_CLS = LivePage

  @classmethod
  def add_cli_parser(cls, subparsers):
    parser = super().add_cli_parser(subparsers)
    parser.add_argument(
        "--urls",
        dest="stories",
        type=cls.parse_cli_stories,
        help="List of urls and durations to load: url,seconds,...")
    return parser

  def __init__(self, *args, stories=None, duration=None, **kwargs):
    if isinstance(stories, _Page):
      stories = [stories]
    for story in stories:
      assert isinstance(story, _Page)
      if duration is not None:
        story.duration = duration
    super().__init__(*args, stories=stories, **kwargs)
