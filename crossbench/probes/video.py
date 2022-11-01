# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import pathlib
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
  import crossbench as cb
import crossbench.probes as probes


class VideoProbe(probes.Probe):
  """
  General-purpose Probe that collects screen-recordings.

  It also produces a timestrip pang and creates merged versions of these files
  for visually comparing various browsers / variants / cb.stories
  """
  NAME = "video"
  VIDEO_QUALITY = ["-vcodec", "libx264", "-crf", "20"]
  IMAGE_FORMAT = "png"
  TIMESTRIP_FILE_SUFFIX = f".timestrip.{IMAGE_FORMAT}"

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._duration = None

  @property
  def results_file_name(self) -> str:
    return f"{self.name}.mp4"

  def pre_check(self, env: cb.env.HostEnvironment):
    super().pre_check(env)
    if env.runner.repetitions > 10:
      env.handle_warning(
          f"Probe={self.NAME} might not be able to merge so many "
          f"repetitions={env.runner.repetitions}.")
    env.check_installed(
        binaries=("ffmpeg", "montage"),
        message="Missing binaries for video probe: %s")

  class Scope(probes.Probe.Scope):
    IMAGE_FORMAT = "png"
    FFMPEG_TIMELINE_TEXT = (
        "drawtext="
        "fontfile=/Library/Fonts/Arial.ttf:"
        "text='%{eif\\:t\\:d}.%{eif\\:t*100-floor(t)*100\\:d}s':"
        "fontsize=h/16:"
        "y=h-line_h-5:x=5:"
        "box=1:boxborderw=15:boxcolor=white")

    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      self._record_process = None
      self._recorder_log_file = None

    def start(self, run: cb.runner.Run):
      browser = run.browser
      cmd = self._record_cmd(browser.x, browser.y, browser.width,
                             browser.height)
      self._recorder_log_file = self.results_file.with_suffix(
          ".recorder.log").open("w")
      self._record_process = self.browser_platform.popen(
          *cmd,
          stdin=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          stdout=self._recorder_log_file)
      assert self._record_process is not None, "Could not start screen recorder"

    def _record_cmd(self, x, y, width, height):
      if self.browser_platform.is_linux:
        env_display = os.environ.get('DISPLAY', ":0.0")
        return ("ffmpeg", "-hide_banner", "-video_size", f"{width}x{height}",
                "-f", "x11grab", "-framerate", "60", "-i",
                f"{env_display}+{x},{y}", self.results_file)
      if self.browser_platform.is_macos:
        return ("/usr/sbin/screencapture", "-v", f"-R{x},{y},{width},{height}",
                self.results_file)
      raise Exception("Invalid platform")

    def stop(self, run: cb.runner.Run):
      if self.browser_platform.is_macos:
        # The mac screencapture stops on the first (arbitrary) input.
        self._record_process.communicate(input=b"stop")
      else:
        self._record_process.terminate()

    def tear_down(self, run: cb.runner.Run):
      self._recorder_log_file.close()
      if self._record_process.poll() is not None:
        self._record_process.wait(timeout=5)
      with tempfile.TemporaryDirectory() as tmp_dir:
        timestrip_file = self._create_time_strip(pathlib.Path(tmp_dir))
      return (self.results_file, timestrip_file)

    def _create_time_strip(self, tmpdir: pathlib.Path):
      logging.info("TIMESTRIP")
      progress_dir = tmpdir / "progress"
      progress_dir.mkdir(parents=True, exist_ok=True)
      timeline_dir = tmpdir / "timeline"
      timeline_dir.mkdir(exist_ok=True)
      # Try detect scene changes / steps
      self.runner_platform.sh(
          "ffmpeg", "-hide_banner", "-i", self.results_file, "-filter_complex",
          "scale=1000:-2,"
          "select='gt(scene\\,0.011)'," + self.FFMPEG_TIMELINE_TEXT, "-vsync",
          "vfr", f"{progress_dir}/%02d.{self.IMAGE_FORMAT}")
      # Extract at regular intervals of 100ms, assuming 60fps input
      every_nth_frame = 60 / 20
      # TODO
      safe_duration = 10
      safe_duration = 2
      self.runner_platform.sh(
          "ffmpeg", "-hide_banner", "-i", self.results_file, "-filter_complex",
          f"trim=duration={safe_duration},"
          "scale=1000:-2,"
          f"select=not(mod(n\\,{every_nth_frame}))," +
          self.FFMPEG_TIMELINE_TEXT, "-vsync", "vfr",
          f"{timeline_dir}/%02d.{self.IMAGE_FORMAT}")

      timeline_strip_file = self.results_file.with_suffix(
          self.probe.TIMESTRIP_FILE_SUFFIX)
      self.runner.platform.sh("montage",
                              f"{timeline_dir}/*.{self.IMAGE_FORMAT}", "-tile",
                              "x1", "-gravity", "NorthWest", "-geometry",
                              "x100", timeline_strip_file)
      return timeline_strip_file

  def merge_repetitions(self, group: cb.runner.RepetitionsRunGroup):
    result_file = group.get_probe_results_file(self)
    timeline_strip_file = result_file.with_suffix(self.TIMESTRIP_FILE_SUFFIX)
    runs = tuple(group.runs)
    if len(runs) == 1:
      # In the simple case just copy the files
      run_result_file, run_timeline_strip_file = runs[0].results[self]
      shutil.copy(run_result_file, result_file)
      shutil.copy(run_timeline_strip_file, timeline_strip_file)
      return (result_file, timeline_strip_file)
    logging.info("TIMESTRIP merge page iterations")
    timeline_strips = (run.results[self][1] for run in runs)
    self.runner_platform.sh("montage", *timeline_strips, "-tile", "1x",
                            "-gravity", "NorthWest", "-geometry", "x100",
                            timeline_strip_file)

    logging.info("VIDEO merge page iterations")
    browser = group.browser
    video_file_inputs = []
    for run in runs:
      video_file_inputs += ["-i", run.results[self][0]]
    draw_text = ("fontfile='/Library/Fonts/Arial.ttf':"
                 f"text='{browser.app_name} {browser.label}':"
                 "fontsize=h/15:"
                 "y=h-line_h-10:x=10:"
                 "box=1:boxborderw=20:boxcolor=white")
    self.runner_platform.sh(
        "ffmpeg", "-hide_banner", *video_file_inputs, "-filter_complex",
        f"hstack=inputs={len(runs)},"
        f"drawtext={draw_text},"
        "scale=3000:-2", *self.VIDEO_QUALITY, result_file)
    return (result_file, timeline_strip_file)

  def merge_browsers(self, group: cb.runner.BrowsersRunGroup):
    """Merge story videos from multiple browser/configurations"""
    groups = list(group.repetitions_groups)
    if len(groups) <= 1:
      return None
    grouped = cb.helper.group_by(
        groups, key=lambda repetitions_group: repetitions_group.story)

    result_dir = group.get_probe_results_file(self)
    result_dir = result_dir / result_dir.stem
    result_dir.mkdir(parents=True)
    return tuple(
        self._merge_stories_for_browser(result_dir, story, repetitions_groups)
        for story, repetitions_groups in grouped.items())

  def _merge_stories_for_browser(
      self, result_dir: pathlib.Path, story: cb.stories.Story,
      repetitions_groups: List[cb.runner.RepetitionsRunGroup]):
    input_files = []
    story = repetitions_groups[0].story
    for repetitions_group in repetitions_groups:
      input_files += ["-i", repetitions_group.results[self][0]]
    result_file = result_dir / f"{story.name}_combined.mp4"
    self.runner_platform.sh("ffmpeg", "-hide_banner", *input_files,
                            "-filter_complex",
                            f"vstack=inputs={len(repetitions_groups)}",
                            *self.VIDEO_QUALITY, result_file)
    return result_file
