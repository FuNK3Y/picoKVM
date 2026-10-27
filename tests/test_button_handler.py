import asyncio
import unittest

from mocks import Pin, TestCase
import board
from button_handler import ButtonHandler


class ButtonHandlerTest(TestCase):
    async def poll(self, handler, presses):
        """Runs the handler while the button follows presses: a list of (level, seconds)."""
        task = asyncio.ensure_future(handler.poll())
        try:
            for level, duration in presses:
                Pin.levels[board.BUTTON] = level
                await asyncio.sleep(duration)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return task

    async def test_press_calls_back_on_release(self):
        calls = []

        async def callback():
            calls.append(1)

        handler = ButtonHandler(board.BUTTON, callback, debounce=0.01)
        await self.poll(handler, [(1, 0.05), (0, 0.05)])
        self.assertEqual(calls, [])  # Still held
        await self.poll(handler, [(1, 0.05)])
        self.assertEqual(calls, [1])

    async def test_callback_errors_are_contained(self):
        async def callback():
            raise OSError("monitor unreachable")

        handler = ButtonHandler(board.BUTTON, callback, debounce=0.01)
        task = await self.poll(handler, [(1, 0.03), (0, 0.03), (1, 0.05)])
        self.assertTrue(task.cancelled())  # Still polling

    async def test_a_glitch_while_held_is_not_a_press(self):
        calls = []

        async def callback():
            calls.append(1)

        handler = ButtonHandler(board.BUTTON, callback, debounce=0.02)
        await self.poll(handler, [(0, 0.05), (1, 0.005), (0, 0.05)])  # Shorter than the debounce
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
