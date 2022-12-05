#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import pathlib
import platform

USE_PYTHON3 = True


def CheckChange(input_api, output_api, on_commit):
  results = []
  # Validate the vpython spec
  results += input_api.RunTests(
      input_api.canned_checks.CheckVPythonSpec(input_api, output_api))
  # Pylint
  files_to_check = [r'^[^\.]+\.py$']
  disabled_warnings = [
      "missing-module-docstring",
      "missing-class-docstring",
      "useless-super-delegation",
      "useless-return",
      "line-too-long",  # Annoying false-positives on URLs
      "cyclic-import",  # TODO: This is not working as expected with pytype
  ]
  pylint_checks = input_api.canned_checks.GetPylint(
      input_api,
      output_api,
      files_to_check=files_to_check,
      disabled_warnings=disabled_warnings)
  results += input_api.RunTests(pylint_checks)
  # License header checks
  results += input_api.canned_checks.CheckLicense(input_api, output_api)
  # Only run test_cli to speed up the presubmit checks
  env = os.environ.copy()
  if platform.system() == "Windows":
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + ";tests"
  else:
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + ":tests"
  if on_commit:
    dirs_to_check = pathlib.Path("tests").glob("**")
    files_to_check = [r'.*test_.*\.py$']
  else:
    # Only check a small subset on upload
    dirs_to_check = [
        "tests",
    ]
    files_to_check = [r'.*test_cli\.py$']

  for dir_to_check in dirs_to_check:
    results += input_api.canned_checks.RunUnitTestsInDirectory(
        input_api,
        output_api,
        directory=dir_to_check,
        env=env,
        files_to_check=files_to_check,
        skip_shebang_check=True,
        run_on_python2=False)
  return results


def CheckChangeOnUpload(input_api, output_api):
  return CheckChange(input_api, output_api, on_commit=False)


def CheckChangeOnCommit(input_api, output_api):
  return CheckChange(input_api, output_api, on_commit=True)
