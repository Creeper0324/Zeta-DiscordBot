"""播放模式回归：自然结束循环当前歌曲，手动跳过仍前进。"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord


class FakeQueue:
    def __init__(self, *items):
        self.items = list(items)
        self.popped = []

    def __len__(self):
        return len(self.items)

    def get_audio(self, index=0):
        return self.items[index] if index < len(self.items) else None

    def pop_audio(self, index=0):
        if not self.items:
            return None
        item = self.items.pop(index)
        self.popped.append(item)
        return item


class RepeatModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = Path("zeta_bot/core.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(item for item in tree.body if getattr(item, "name", None) == "play_next")
        self.play_audio = AsyncMock()
        self.audio_lib = SimpleNamespace(unlock_audio=Mock())
        self.console = SimpleNamespace(rp=AsyncMock(), on_error=AsyncMock())
        self.guild_obj = None
        namespace = {
            "discord": discord,
            "guild_lib": SimpleNamespace(get_guild=lambda _: self.guild_obj),
            "audio_lib_main": self.audio_lib,
            "console": self.console,
            "play_audio": self.play_audio,
            "utils": SimpleNamespace(PrintType=SimpleNamespace(ERROR=1)),
            "_playback_states": {},
            "_close_prefetched_stream": Mock(),
            "embed_send": AsyncMock(),
            "icon": SimpleNamespace(url=lambda _: ""),
            "icon_lib": SimpleNamespace(files=lambda _: []),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "zeta_bot/core.py", "exec"), namespace)
        self.play_next = namespace["play_next"]
        self.ctx = SimpleNamespace(guild=SimpleNamespace(id=42, voice_client=None))

    async def test_natural_finish_replays_without_removing_current_track(self):
        current = Mock()
        current.get_title.return_value = "current"
        queue = FakeQueue(current, Mock())
        self.guild_obj = SimpleNamespace(
            get_playlist=lambda: queue,
            get_play_mode=lambda: 1,
            refresh_list_view=AsyncMock(),
        )

        await self.play_next(self.ctx)

        self.play_audio.assert_awaited_once_with(self.ctx, current, response=None)
        self.assertEqual(queue.items[0], current)
        self.assertEqual(queue.popped, [])

    async def test_manual_advance_bypasses_repeat(self):
        current, following = Mock(), Mock()
        current.get_title.return_value = "current"
        queue = FakeQueue(current, following)
        self.guild_obj = SimpleNamespace(
            get_playlist=lambda: queue,
            get_play_mode=lambda: 1,
            refresh_list_view=AsyncMock(),
        )

        await self.play_next(self.ctx, force_advance=True)

        self.assertEqual(queue.popped, [current])
        self.play_audio.assert_awaited_once_with(self.ctx, following, response=None)
        self.assertEqual(queue.items, [following])


if __name__ == "__main__":
    unittest.main()
