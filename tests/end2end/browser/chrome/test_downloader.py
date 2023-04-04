# Copyright 2023 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import pytest
import sys
from crossbench.browsers.chrome.downloader import ChromeDownloader
from tests.end2end.helper import End2EndTestCase


class ChromeDownloaderTestCase(End2EndTestCase):
  __test__ = True

  def setUp(self) -> None:
    super().setUp()
    if not self.platform.which("gsutil"):
      self.skipTest("Missing required 'gsutil', skipping test.")

  def test_download_major_version(self) -> None:
    self.assertListEqual(list(self.output_dir.iterdir()), [])
    app_path = ChromeDownloader.load("chrome-M111", self.platform,
                                     self.output_dir)
    self.assertTrue(app_path.exists())
    version = self.platform.app_version(app_path)
    self.assertIn("111", version)
    self.assertSetEqual(
        set(self.output_dir.iterdir()), {app_path, self.output_dir / "archive"})

  def test_download_specific_version(self) -> None:

    self.assertListEqual(list(self.output_dir.iterdir()), [])
    version_str = "111.0.5563.110"
    app_path = ChromeDownloader.load(f"chrome-{version_str}", self.platform,
                                     self.output_dir)
    self.assertTrue(app_path.exists())
    version = self.platform.app_version(app_path)
    self.assertIn(version_str, version)
    archive_dir = self.output_dir / "archive"
    self.assertSetEqual(set(self.output_dir.iterdir()), {app_path, archive_dir})
    # Re-downloading should work as well
    app_path = ChromeDownloader.load(f"chrome-{version_str}", self.platform,
                                     self.output_dir)
    self.assertTrue(app_path.exists())
    self.assertSetEqual(set(self.output_dir.iterdir()), {app_path, archive_dir})
    version = self.platform.app_version(app_path)
    self.assertIn(version_str, version)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
