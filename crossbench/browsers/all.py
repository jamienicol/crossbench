# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench.browsers.browser import (BROWSERS_CACHE, Browser,
                                         convert_flags_to_label)
from crossbench.browsers.chrome import (Chrome, ChromeAppleScript,
                                        ChromeWebDriver, ChromeWebDriverAndroid)
from crossbench.browsers.chromium import (Chromium, ChromiumAppleScript,
                                          ChromiumWebDriver,
                                          ChromiumWebDriverAndroid)
from crossbench.browsers.edge import Edge, EdgeWebDriver
from crossbench.browsers.firefox import Firefox, FirefoxWebDriver, FirefoxWebDriverAndroid
from crossbench.browsers.safari import (Safari, SafariAppleScript,
                                        SafariWebDriver)
from crossbench.browsers.webdriver import RemoteWebDriver

__all__ = (
    "BROWSERS_CACHE",
    "Browser",
    "Chrome",
    "ChromeAppleScript",
    "ChromeWebDriver",
    "ChromeWebDriverAndroid",
    "Chromium",
    "ChromiumAppleScript",
    "ChromiumWebDriver",
    "ChromiumWebDriverAndroid",
    "Edge",
    "EdgeWebDriver",
    "Firefox",
    "FirefoxWebDriver",
    "FirefoxWebDriverAndroid",
    "RemoteWebDriver",
    "Safari",
    "SafariAppleScript",
    "SafariWebDriver",
    "convert_flags_to_label",
)
