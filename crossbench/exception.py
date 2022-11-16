# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
import traceback
from types import TracebackType
from typing import Dict, List, Optional, Tuple, Type

from crossbench import helper

TInfoStack = Tuple[str, ...]

TExceptionTypes = Tuple[Type[BaseException], ...]


@dataclass
class Entry:
  traceback: str
  exception: BaseException
  info_stack: TInfoStack


class ContextManager:

  def __init__(self, exception_handler: Handler,
               exception_types: TExceptionTypes, entries: Tuple[str]):
    self._handler = exception_handler
    self._exception_types = exception_types
    self._added_info_stack_entries = entries
    self._previous_info_stack: TInfoStack = ()

  def __enter__(self):
    self._handler._pending_exceptions.clear()
    self._previous_info_stack = self._handler.info_stack
    self._handler._info_stack = self._previous_info_stack + (
        self._added_info_stack_entries)

  def __exit__(self, exception_type: Optional[Type[BaseException]],
               exception_value: Optional[BaseException],
               traceback: Optional[TracebackType]) -> bool:
    if not exception_value:
      self._handler._info_stack = self._previous_info_stack
      return False
    if self._exception_types and issubclass(exception_type,
                                            self._exception_types):
      # Handle matching exceptions directly here and prevent further
      # exception handlers by returning True.
      self._handler.handle(exception_value)
      self._handler._info_stack = self._previous_info_stack
      return True
    if exception_value not in self._handler._pending_exceptions:
      self._handler._pending_exceptions[
          exception_value] = self._handler.info_stack


class Handler:

  def __init__(self, throw: bool = False):
    self._exceptions: List[Entry] = []
    self.throw: bool = throw
    # The info_stack adds additional meta information to handle exceptions.
    # Unlike the source-based backtrace, this can contain dynamic information
    # for easier debugging.
    self._info_stack: TInfoStack = ()
    # Associates raised exception with the info_stack at that time for later
    # use in the `handle` method.
    # This is cleared whenever we enter a  new ContextManager.
    self._pending_exceptions: Dict[BaseException, TInfoStack] = {}

  @property
  def is_success(self) -> bool:
    return len(self._exceptions) == 0

  @property
  def info_stack(self) -> TInfoStack:
    return self._info_stack

  @property
  def exceptions(self) -> List[Entry]:
    return self._exceptions

  def assert_success(self,
                     exception_cls: Type[BaseException] = AssertionError,
                     message: Optional[str] = None):
    if self.is_success:
      return
    self.log()
    if message is None:
      message = f"Got Exceptions: {self}"
    raise exception_cls(message)

  def info(self, *stack_entries: str) -> ContextManager:
    return ContextManager(self, tuple(), stack_entries)

  def handler(self,
              *stack_entries: str,
              exceptions: TExceptionTypes = (Exception,)) -> ContextManager:
    return ContextManager(self, exceptions, stack_entries)

  def extend(self, handler: Handler, is_nested: bool = False):
    if is_nested:
      self._extend_with_prepended_stack_info(handler)
    else:
      self._exceptions.extend(handler.exceptions)

  def _extend_with_prepended_stack_info(self, handler: Handler):
    for entry in handler.exceptions:
      merged_info_stack = self.info_stack + entry.info_stack
      merged_entry = Entry(entry.traceback, entry.exception, merged_info_stack)
      self._exceptions.append(merged_entry)

  def handle(self, e: BaseException):
    if isinstance(e, KeyboardInterrupt):
      # Fast exit on KeyboardInterrupts for a better user experience.
      sys.exit(0)
    tb: str = traceback.format_exc()
    stack = self.info_stack
    if e in self._pending_exceptions:
      stack = self._pending_exceptions[e]
    self._exceptions.append(Entry(tb, e, stack))
    logging.info("Intermediate Exception: %s", e)
    logging.debug(tb)
    if self.throw:
      raise

  def log(self):
    if self.is_success:
      return
    logging.error("ERRORS occurred:")
    for entry in self._exceptions:
      logging.debug("-" * 80)
      logging.debug(entry.exception)
      logging.debug(entry.traceback)
    for info_stack, entries in helper.group_by(
        self._exceptions, key=lambda entry: tuple(entry.info_stack)).items():
      logging.error("=" * 80)
      if info_stack:
        info = "Info: "
        joiner = "\n" + (" " * (len(info) - 2)) + "> "
        logging.error(f"{info}{joiner.join(info_stack)}")
      for entry in entries:
        logging.error("- " * 40)
        logging.error(f"Type: {entry.exception.__class__.__name__}:")
        logging.error(f"      {entry.exception}")

  def to_json(self) -> list:
    return [{
        "title": str(entry.exception),
        "trace": str(entry.traceback),
        "info_stack": entry.info_stack
    } for entry in self._exceptions]

  def __str__(self) -> str:
    return "\n".join(list(entry.exception for entry in self._exceptions))
