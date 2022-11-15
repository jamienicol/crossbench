# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

import crossbench as cb
from crossbench import runner


class ExceptionHandlerTestCase(unittest.TestCase):

  def test_empty(self):
    handler = runner.ExceptionHandler()
    self.assertTrue(handler.is_success)
    self.assertListEqual(handler.exceptions, [])
    self.assertListEqual(handler.to_json(), [])
    with mock.patch("logging.error") as logging_mock:
      handler.log()
    # No exceptions => no error output
    logging_mock.assert_not_called()

  def test_handle_exception(self):
    handler = runner.ExceptionHandler()
    exception = ValueError("custom message")
    try:
      raise exception
    except ValueError as e:
      handler.handle(e)
    self.assertFalse(handler.is_success)
    serialized = handler.to_json()
    self.assertEqual(len(serialized), 1)
    self.assertEqual(serialized[0]["title"], str(exception))
    with mock.patch("logging.debug") as logging_mock:
      handler.log()
    logging_mock.assert_has_calls([mock.call(exception)])

  def test_handle_rethrow(self):
    handler = runner.ExceptionHandler(throw=True)
    exception = ValueError("custom message")
    with self.assertRaises(ValueError) as cm:
      try:
        raise exception
      except ValueError as e:
        handler.handle(e)
    self.assertEqual(cm.exception, exception)
    self.assertFalse(handler.is_success)
    serialized = handler.to_json()
    self.assertEqual(len(serialized), 1)
    self.assertEqual(serialized[0]["title"], str(exception))

  def test_info_stack(self):
    handler = runner.ExceptionHandler(throw=True)
    exception = ValueError("custom message")
    with self.assertRaises(ValueError) as cm, handler.info("info 1", "info 2"):
      self.assertTupleEqual(handler.info_stack, ("info 1", "info 2"))
      try:
        raise exception
      except ValueError as e:
        handler.handle(e)
    self.assertEqual(cm.exception, exception)
    self.assertFalse(handler.is_success)
    self.assertEqual(len(handler.exceptions), 1)
    entry = handler.exceptions[0]
    self.assertTupleEqual(entry.info_stack, ("info 1", "info 2"))
    serialized = handler.to_json()
    self.assertEqual(len(serialized), 1)
    self.assertEqual(serialized[0]["title"], str(exception))
    self.assertEqual(serialized[0]["info_stack"], ("info 1", "info 2"))

  def test_info_stack_logging(self):
    handler = runner.ExceptionHandler()
    try:
      with handler.info("info 1", "info 2"):
        raise ValueError("custom message")
    except ValueError as e:
      handler.handle(e)
    with self.assertLogs(level="ERROR") as cm:
      handler.log()
    output = "\n".join(cm.output)
    self.assertIn("info 1", output)
    self.assertIn("info 2", output)
    self.assertIn("custom message", output)

  def test_handle_keyboard_interrupt(self):
    handler = runner.ExceptionHandler()
    keyboard_interrupt = KeyboardInterrupt()
    with mock.patch("sys.exit", side_effect=ValueError) as exit_mock:
      with self.assertRaises(ValueError) as cm:
        try:
          raise keyboard_interrupt
        except KeyboardInterrupt as e:
          handler.handle(e)
      self.assertNotEqual(cm.exception, keyboard_interrupt)
    exit_mock.assert_called_once_with(0)

  def test_extend(self):
    handler_1 = runner.ExceptionHandler()
    try:
      raise ValueError("error_1")
    except ValueError as e:
      handler_1.handle(e)
    handler_2 = runner.ExceptionHandler()
    try:
      raise ValueError("error_2")
    except ValueError as e:
      handler_2.handle(e)
    handler_3 = runner.ExceptionHandler()
    handler_4 = runner.ExceptionHandler()
    self.assertFalse(handler_1.is_success)
    self.assertFalse(handler_2.is_success)
    self.assertTrue(handler_3.is_success)
    self.assertTrue(handler_4.is_success)

    self.assertEqual(len(handler_1.exceptions), 1)
    self.assertEqual(len(handler_2.exceptions), 1)
    handler_2.extend(handler_1)
    self.assertEqual(len(handler_2.exceptions), 2)
    self.assertFalse(handler_1.is_success)
    self.assertFalse(handler_2.is_success)

    self.assertEqual(len(handler_1.exceptions), 1)
    self.assertEqual(len(handler_3.exceptions), 0)
    self.assertEqual(len(handler_4.exceptions), 0)
    handler_3.extend(handler_1)
    handler_3.extend(handler_4)
    self.assertEqual(len(handler_3.exceptions), 1)
    self.assertFalse(handler_3.is_success)
    self.assertTrue(handler_4.is_success)

  def test_extend_nested(self):
    handler_1 = runner.ExceptionHandler()
    handler_2 = runner.ExceptionHandler()
    exception_1 = ValueError("error_1")
    exception_2 = ValueError("error_2")
    with handler_1.handler("info 1", "info 2", exceptions=(ValueError,)):
      raise exception_1
    self.assertEqual(len(handler_1.exceptions), 1)
    self.assertEqual(len(handler_2.exceptions), 0)
    with handler_1.info("info 1", "info 2"):
      with handler_2.handler("info 3", "info 4", exceptions=(ValueError,)):
        raise exception_2
      handler_1.extend(handler_2, is_nested=True)
    self.assertEqual(len(handler_1.exceptions), 2)
    self.assertEqual(len(handler_2.exceptions), 1)
    self.assertTupleEqual(handler_1.exceptions[0].info_stack,
                          ("info 1", "info 2"))
    self.assertTupleEqual(handler_1.exceptions[1].info_stack,
                          ("info 1", "info 2", "info 3", "info 4"))
    self.assertTupleEqual(handler_2.exceptions[0].info_stack,
                          ("info 3", "info 4"))
