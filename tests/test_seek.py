"""播放进度与跳转功能的离线回归测试。"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import utils
import discord


def load_functions(*names):
    tree = ast.parse(Path("zeta_bot/core.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    namespace = {
        "Dict": Dict, "Optional": Optional,
        "audio": SimpleNamespace(Audio=object), "time": Mock(),
        "discord": discord, "_playback_states": {},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "zeta_bot/core.py", "exec"), namespace)
    return namespace


class SeekParserAndClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_functions(
            "_parse_seek_timestamp", "_new_playback_session", "_playback_position",
            "_advance_playback_position", "_invalidate_playback_session",
            "_PositionTrackingAudioSource",
        )

    def setUp(self):
        self.ns["_playback_states"].clear()

    def test_accepts_seconds_minutes_and_hours(self):
        parse = self.ns["_parse_seek_timestamp"]
        self.assertEqual(parse("314"), 314)
        self.assertEqual(parse("5:14"), 314)
        self.assertEqual(parse("1:02:03"), 3723)
        self.assertEqual(parse("5：14"), 314)

    def test_rejects_invalid_timestamp_components(self):
        parse = self.ns["_parse_seek_timestamp"]
        for value in ("", "abc", "1:60", "1:60:00", "-1", "1::2"):
            with self.assertRaises(ValueError, msg=value):
                parse(value)

    def test_clock_advances_by_audio_frames_and_ignores_stale_session(self):
        item = SimpleNamespace(get_duration=lambda: 600, get_uid=lambda: "song")
        session = self.ns["_new_playback_session"](7, item, position=314)
        # 192000字节等于1秒48kHz、双声道、16位PCM。
        self.ns["_advance_playback_position"](7, session, 192000 * 6)
        self.assertEqual(self.ns["_playback_position"](7), 320)
        self.ns["_advance_playback_position"](7, object(), 192000 * 20)
        self.assertEqual(self.ns["_playback_position"](7), 320)

    def test_audio_source_counts_only_bytes_actually_read(self):
        item = SimpleNamespace(get_duration=lambda: 600, get_uid=lambda: "song")
        session = self.ns["_new_playback_session"](7, item, position=10)
        source = SimpleNamespace(
            read=Mock(side_effect=[b"x" * 3840, b""]),
            is_opus=lambda: False, cleanup=Mock(),
        )
        tracked = self.ns["_PositionTrackingAudioSource"](source, 7, session)
        self.assertEqual(len(tracked.read()), 3840)
        self.assertEqual(tracked.read(), b"")
        self.assertEqual(self.ns["_playback_states"][7]["position"], 10.02)
        tracked.cleanup()
        source.cleanup.assert_called_once()


class SeekCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = load_functions("_parse_seek_timestamp", "seek_callback")
        self.audio = SimpleNamespace(
            get_duration=lambda: 300, get_duration_str=lambda: "05:00",
            get_title=lambda: "测试歌曲",
        )
        self.playlist = SimpleNamespace(
            is_empty=lambda: False, get_audio=lambda _: self.audio,
        )
        self.voice = SimpleNamespace(
            is_playing=lambda: True, is_paused=lambda: False, stop=Mock(),
        )
        self.guild_state = SimpleNamespace(
            get_playlist=lambda: self.playlist, refresh_list_view=AsyncMock(),
        )
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=7, voice_client=self.voice), author="tester",
        )
        self.ns.update({
            "guild_lib": SimpleNamespace(
                check=AsyncMock(), get_guild=lambda _: self.guild_state,
            ),
            "audio_lib_main": object(), "embed_respond": AsyncMock(),
            "icon": SimpleNamespace(url=lambda _: "icon"),
            "icon_lib": SimpleNamespace(files=lambda _: []), "orange": object(),
            "_invalidate_playback_session": Mock(), "play_audio": AsyncMock(),
            "console": SimpleNamespace(on_error=AsyncMock(), rp=AsyncMock()),
            "utils": utils,
        })

    async def test_rejects_position_beyond_duration_without_stopping(self):
        await self.ns["seek_callback"](self.ctx, "5:01")
        self.voice.stop.assert_not_called()
        self.ns["play_audio"].assert_not_awaited()
        message = self.ns["embed_respond"].await_args.args[1]
        self.assertIn("超过", message)

    async def test_valid_seek_restarts_same_audio_without_changing_queue(self):
        await self.ns["seek_callback"](self.ctx, "2:30")
        self.voice.stop.assert_called_once()
        self.ns["play_audio"].assert_awaited_once_with(
            self.ctx, self.audio, start_position=150,
            start_paused=False, update_playing_message=False,
        )
        self.guild_state.refresh_list_view.assert_awaited_once()


class SeekSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_ffmpeg_callback_does_not_advance_queue(self):
        ns = load_functions("_handle_playback_after")
        ns.update({
            "Optional": Optional,
            "_playback_states": {7: {"session_id": object()}},
            "_fallback_and_replay": AsyncMock(), "play_next": AsyncMock(),
        })
        # 重新执行，以便函数使用上面这组依赖。
        tree = ast.parse(Path("zeta_bot/core.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body
                    if getattr(n, "name", None) == "_handle_playback_after")
        exec(compile(ast.Module(body=[node], type_ignores=[]), "zeta_bot/core.py", "exec"), ns)
        ctx = SimpleNamespace(guild=SimpleNamespace(id=7))
        stream = SimpleNamespace(is_stream=lambda: True)

        await ns["_handle_playback_after"](
            ctx, stream, returncode=None, session_id=object(), start_position=120,
        )

        ns["_fallback_and_replay"].assert_not_awaited()
        ns["play_next"].assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
