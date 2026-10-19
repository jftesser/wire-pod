"""Optional conversation expressions, independent of microphone/speaker clocks.

Owns only the face and head. A future navigation policy can share this coordinator
and its fresh robot-state checks; no wheel or lift commands are issued here.
"""
import asyncio
import contextlib
import math
import time

import numpy as np
from PIL import Image, ImageDraw
from vector_audio import p

UNSAFE = sum(p.RobotStatus.Value(name) for name in (
    'ROBOT_STATUS_IS_PICKED_UP', 'ROBOT_STATUS_IS_FALLING',
    'ROBOT_STATUS_CLIFF_DETECTED', 'ROBOT_STATUS_ARE_WHEELS_MOVING',
    'ROBOT_STATUS_IS_BEING_HELD', 'ROBOT_STATUS_IS_PATHING'))


def face_frame(state, blink=False, alternate=False):
    """184x96 RGB565 in the big-endian byte order used by the SDK screen API."""
    image = Image.new('RGB', (184, 96))
    draw = ImageDraw.Draw(image)
    dx = 5 if state == 'thinking' else 0
    height = 3 if blink else (34 if state == 'speaking' and alternate else 42)
    for x in (38, 108):
        y = (96-height)//2
        draw.rounded_rectangle((x+dx, y, x+dx+38, y+height), radius=min(9, height//2), fill=(75, 255, 120))
    rgb = np.asarray(image, dtype=np.uint16)
    encoded = ((rgb[:,:,0]>>3)<<11) | ((rgb[:,:,1]>>2)<<5) | (rgb[:,:,2]>>3)
    return encoded.astype('>u2').tobytes()


FRAMES = {(state, blink, alternate): face_frame(state, blink, alternate)
          for state in ('listening', 'thinking', 'speaking')
          for blink in (False, True) for alternate in (False, True)}


class ConversationBehaviors:
    def __init__(self, robot, player, session):
        self.robot, self.player, self.session = robot, player, session
        self.mode = 'off'
        self.state = 'off'
        self.error = None
        self.task = self.head = None
        self.observed = None
        self.observed_at = 0
        self.last_nod = -math.inf
        self.next_tag = p.FIRST_SDK_TAG
        self.active_tag = None
        self.frames_sent = self.nods_completed = 0

    def observe(self, robot_state):
        self.observed, self.observed_at = robot_state, time.monotonic()

    def safe_head(self):
        state = self.observed
        return bool(self.mode == 'head' and not self.error
            and not getattr(self.robot, 'control_error', None)
            and state is not None and time.monotonic()-self.observed_at < 1
            and not state.status & UNSAFE
            and abs(state.left_wheel_speed_mmps) < 1 and abs(state.right_wheel_speed_mmps) < 1
            and math.isfinite(state.head_angle_rad)
            and math.radians(-22) <= state.head_angle_rad <= math.radians(45))

    async def cancel_head(self):
        if self.head:
            self.head.cancel()
            await asyncio.gather(self.head, return_exceptions=True)
            self.head = None

    async def nod(self):
        original = self.observed.head_angle_rad
        # Nod down from the observed pose, then return; never re-home the head.
        target = max(math.radians(-22), min(math.radians(45), original-math.radians(8)))
        try:
            for angle in (target, original):
                if not self.safe_head():
                    return
                tag = self.next_tag
                self.next_tag = p.FIRST_SDK_TAG if tag == p.LAST_SDK_TAG else tag+1
                self.active_tag = tag
                response = await self.robot.stub.SetHeadAngle(p.SetHeadAngleRequest(
                    angle_rad=angle, max_speed_rad_per_sec=.35, accel_rad_per_sec2=1,
                    duration_sec=.4, id_tag=tag, num_retries=0), timeout=1.5)
                if response.result.code != 0:
                    raise RuntimeError('Head action did not complete.')
                self.active_tag = None
            self.nods_completed += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = 'Head expressions unavailable.'
        finally:
            if self.active_tag is not None:
                with contextlib.suppress(Exception):
                    await self.robot.stub.CancelActionByIdTag(p.CancelActionByIdTagRequest(id_tag=self.active_tag), timeout=.5)
                self.active_tag = None

    async def run(self):
        previous = None
        next_frame = 0
        started = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if self.head and (self.head.done() or not self.safe_head()):
                    await self.cancel_head()
                if self.mode == 'off' or self.error or getattr(self.robot, 'control_error', None):
                    self.state = 'degraded' if self.error else 'off'
                    previous = None
                else:
                    state = ('speaking' if self.player.clip is not None else
                             'thinking' if self.session.backend_pending else 'listening')
                    self.state = state
                    if state == 'speaking' and previous != state and now-self.last_nod >= 12 and self.safe_head() and not self.head:
                        self.last_nod = now
                        self.head = asyncio.create_task(self.nod())
                    if state != previous or now >= next_frame:
                        blink = (now-started) % 4 < .2
                        image = FRAMES[state, blink, int((now-started)*2.5)%2 == 1]
                        await self.robot.stub.DisplayFaceImageRGB(p.DisplayFaceImageRGBRequest(
                            face_data=image, duration_ms=700, interrupt_running=True), timeout=.6)
                        self.frames_sent += 1
                        next_frame = now+.4
                    previous = state
                await asyncio.sleep(.1)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error, self.state = 'Face expressions unavailable.', 'degraded'
        finally:
            await self.cancel_head()
            # Face images expire in <=700 ms; releasing SDK control restores
            # ordinary eyes. Never send another motor command during cleanup.

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.cancel_head()
        self.state = 'off'
