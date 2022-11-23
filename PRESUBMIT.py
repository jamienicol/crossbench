#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import os
import sys
import glob
from pathlib import Path
USE_PYTHON3 = True


def CheckChangeOnUpload(input_api, output_api):
  results = []
  # Validate the vpython spec
  results.extend(
      input_api.RunTests(
          input_api.canned_checks.CheckVPythonSpec(input_api, output_api)))
  # TODO: It will be good to add pylint checks here.
  # Currently the code has a bunch of pylint errors that need to be fixed
  # before we can enable pylint presubmit check.
  # Uncomment the line below to enable the pylint presubmit check.
  #
  # pylint_checks = input_api.canned_checks.GetPylint(input_api, output_api)
  # results += input_api.RunTests(pylint_checks)
  # Run Python unittests.
  test_file_pattern = r'.*test_.*\.py$'
  test_directories = GetTestDirectories(input_api, test_file_pattern)
  tests = []
  for test_dir in test_directories:
    test_cmds = input_api.canned_checks.GetUnitTestsInDirectory(
        input_api,
        output_api,
        test_dir, [test_file_pattern],
        run_on_python3=True,
        run_on_python2=False,
        skip_shebang_check=True)
    tests.extend(test_cmds)
  results += input_api.RunTests(tests)

  return results


def CheckChangeOnCommit(input_api, output_api):
  return CheckChangeOnUpload(input_api, output_api)


def GetTestDirectories(input_api, test_file_filter):
  tests_root_dir = os.path.join(input_api.PresubmitLocalPath(), 'tests')
  test_directories = set()
  # Get all the directories under "tests" that have files that
  # follow the test_file_filter naming format
  for root, subdir, files in os.walk(tests_root_dir):
    if (os.path.isdir(root) and not root.endswith('__pycache__') and
        any(True for f in files if input_api.re.match(test_file_filter, f))):
      test_directories.add(root)
  return test_directories
