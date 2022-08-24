#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
from pathlib import Path

import crossbench.cli

if __name__ == "__main__":
  cli = crossbench.cli.CrossBenchCLI()
  cli.run(sys.argv[1:])
