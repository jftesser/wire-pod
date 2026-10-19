"""Optional conversation expressions, independent of microphone/speaker clocks.

Coordinates face/head and finite supervised motor actions. Natural mode leaves
ordinary robot autonomy active between explicitly requested SDK gestures.
"""
import asyncio
import contextlib
import math
import time

import numpy as np
from PIL import Image, ImageDraw
from vector_audio import p
from legacy_animations import catalog, CANCEL_ANIMATION
from robot_motion import RobotMotion, PREVIEWS, validate_motion

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
        self.autonomy = False
        self.autonomy_pending = False
        self.motion = 'off'
        self.closing = False
        self.lease_held = False
        self.motors = RobotMotion(self)
        self.nod_depth, self.nod_interval = 8, 12
        self.legacy_enabled = False
        self.available_animations = set()
        self.legacy_error = None
        self.catalog_checked = False
        self.clips = catalog()
        self.gesture = None
        self.gesture_kind = None
        self.gesture_uses_head = False
        self.animation_name = None
        self.last_expression = None
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

    def allocate_tag(self):
        tag = self.next_tag
        self.next_tag = p.FIRST_SDK_TAG if tag == p.LAST_SDK_TAG else tag+1
        return tag

    @contextlib.asynccontextmanager
    async def control_if_needed(self):
        if not self.autonomy:
            yield
            return
        async with self.robot.control():
            self.lease_held = True
            try:
                # Let ordinary behavior cancellations and fresh stationary state
                # arrive before dispatching a new SDK action.
                await asyncio.sleep(.8)
                yield
            finally:
                self.lease_held = False

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

    async def nod(self, depth=None):
        depth = self.nod_depth if depth is None else depth
        if type(depth) is not int or not 2 <= depth <= 20:
            raise ValueError('Nod depth must be2–20degrees.')
        original = self.observed.head_angle_rad
        # Nod down from the observed pose, then return; never re-home the head.
        target = max(math.radians(-22), min(math.radians(45), original-math.radians(depth)))
        try:
            for angle in (target, original):
                if not self.safe_head():
                    return
                tag = self.allocate_tag()
                self.active_tag = tag
                response = await self.robot.stub.SetHeadAngle(p.SetHeadAngleRequest(
                    angle_rad=angle, max_speed_rad_per_sec=.35, accel_rad_per_sec2=1,
                    duration_sec=.4, id_tag=tag, num_retries=0), timeout=1.5)
                if response.result.code != 0:
                    raise RuntimeError('Head action did not complete.')
                self.active_tag = None
            self.nods_completed += 1
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = 'Head expressions unavailable.'
        finally:
            if self.active_tag is not None:
                with contextlib.suppress(Exception):
                    await self.robot.stub.CancelActionByIdTag(p.CancelActionByIdTagRequest(id_tag=self.active_tag), timeout=.5)
                self.active_tag = None

    async def load_animations(self):
        async with self.control_if_needed():
            await self._load_animations_owned()

    async def _load_animations_owned(self):
        self.catalog_checked = True
        self.animation_name = 'preflight'
        self.gesture_uses_head = False
        try:
            await self.cancel_head()
            # ListAnimations times out, and the engine can report complete for
            # a missing clip. Probe a known quiet FACE-ONLY clip and reject an
            # implausibly short result. Never fall back to original noisy clips.
            # The gateway's completion channel is shared with ordinary behavior.
            # Let control-grant cancellations drain before the first probe.
            await asyncio.sleep(.8)
            probe = self.clips['happy']
            started = time.monotonic()
            response = await self.robot.stub.PlayAnimation(p.PlayAnimationRequest(
                animation=p.Animation(name=probe['name']), loops=1,
                ignore_body_track=True, ignore_head_track=True, ignore_lift_track=True), timeout=probe['duration_ms']/1000+1.5)
            if response.result != p.BEHAVIOR_COMPLETE_STATE or response.animation.name != probe['name'] or time.monotonic()-started < probe['duration_ms']/1000*.7:
                raise RuntimeError('Quiet animation preflight did not complete plausibly.')
            self.available_animations = set(self.clips)
            self.legacy_error = None
        except Exception:
            self.available_animations = set()
            self.legacy_error = 'Quiet legacy assets are unavailable.'
        finally:
            self.animation_name = None

    def capabilities(self):
        return dict(nod_depth=self.nod_depth, nod_interval=self.nod_interval,
            autonomy=self.autonomy, autonomy_pending=self.autonomy_pending, motion=self.motion, motor_action=self.motors.action,
            motor_actions_completed=self.motors.completed,
            legacy_animations=self.legacy_enabled, animation_catalog=sorted(self.available_animations),
            animation_error=self.legacy_error, last_expression=self.last_expression)

    def start_expression(self, name, depth=0):
        if name in PREVIEWS:
            if depth != 0:
                raise ValueError('Nod depth does not apply to motor actions.')
            return self.start_motion(*PREVIEWS[name])
        if name not in ('nod', 'blink', *self.clips) or type(depth) is not int or not 0 <= depth <= 20 or depth == 1:
            raise ValueError('Choose a known expression and nod depth0or2–20.')
        if name != 'nod' and depth != 0:
            raise ValueError('Depth applies only to nods.')
        if self.mode == 'off' or self.error or getattr(self.robot, 'control_error', None):
            raise ValueError('Conversation expressions are disabled or unavailable.')
        if self.animation_name or (self.gesture and not self.gesture.done()):
            raise ValueError('An expression or its preflight is already running.')
        if name == 'nod' and not self.safe_head():
            raise ValueError('Fresh robot state does not permit a head gesture.')
        if name not in ('nod', 'blink') and (not self.legacy_enabled or name not in self.available_animations):
            raise ValueError('This quiet legacy expression is disabled or unavailable.')
        self.gesture_uses_head = name == 'nod' or (name != 'blink' and self.safe_head())
        self.gesture_kind = 'expression'
        self.last_expression = dict(name=name, status='running', head_tracks=self.gesture_uses_head)
        self.gesture = asyncio.create_task(self._expression(name, depth))
        return self.gesture

    async def stop_native_animation(self):
        # PlayAnimation actions are assigned internal engine tags, not SDK tags.
        # Queueing the face-only cancellation clip NOW cancels the old action.
        with contextlib.suppress(Exception):
            await self.robot.stub.PlayAnimation(p.PlayAnimationRequest(
                animation=p.Animation(name=CANCEL_ANIMATION), loops=1,
                ignore_body_track=True, ignore_head_track=True, ignore_lift_track=True), timeout=.6)
        if self.gesture_uses_head:
            with contextlib.suppress(Exception):
                await self.robot.stub.StopAllMotors(p.StopAllMotorsRequest(), timeout=.5)

    async def _expression(self, name, depth):
        try:
            async with self.control_if_needed():
                return await self._expression_owned(name, depth)
        except asyncio.CancelledError:
            self.last_expression = dict(name=name, status='cancelled', error='Expression cancelled.')
            raise
        except Exception:
            self.last_expression = dict(name=name, status='failed', error='Expression control unavailable.')
            return self.last_expression

    async def _expression_owned(self, name, depth):
        native = name not in ('nod', 'blink')
        completed = False
        error = None
        try:
            await self.cancel_head()
            if name == 'nod':
                completed = bool(await self.nod(depth or self.nod_depth))
            elif name == 'blink':
                self.animation_name = name
                await self.robot.stub.DisplayFaceImageRGB(p.DisplayFaceImageRGBRequest(
                    face_data=FRAMES['listening', True, False], duration_ms=200, interrupt_running=True), timeout=.6)
                await asyncio.sleep(.18)
                completed = True
            else:
                self.animation_name = name
                clip = self.clips[name]
                started = time.monotonic()
                response = await self.robot.stub.PlayAnimation(p.PlayAnimationRequest(
                    animation=p.Animation(name=clip['name']), loops=1,
                    ignore_body_track=True, ignore_lift_track=True,
                    ignore_head_track=not self.gesture_uses_head), timeout=clip['duration_ms']/1000+1.5)
                completed = (response.result == p.BEHAVIOR_COMPLETE_STATE and response.animation.name == clip['name']
                    and time.monotonic()-started >= clip['duration_ms']/1000*.7
                    and (not self.gesture_uses_head or self.safe_head()))
                if not completed:
                    self.available_animations.discard(name)
                    error = 'Robot did not complete the animation.'
        except asyncio.CancelledError:
            error = 'Expression cancelled.'
            raise
        except Exception:
            error = 'Expression playback failed.'
        finally:
            if native and not completed:
                await self.stop_native_animation()
            self.animation_name = None
            self.last_expression = dict(name=name, status='completed' if completed else 'cancelled' if error == 'Expression cancelled.' else 'failed',
                head_tracks=self.gesture_uses_head, error=error)
        return self.last_expression

    async def cancel_expression(self):
        if self.gesture and not self.gesture.done():
            self.gesture.cancel()
            await asyncio.gather(self.gesture, return_exceptions=True)

    def start_motion(self, action, amount=0):
        validate_motion(action, amount)
        if action == 'stop':
            return asyncio.create_task(self.stop_motion())
        if self.animation_name or (self.gesture and not self.gesture.done()):
            raise ValueError('Another expression or motor action is running.')
        reason = self.motors.reason(action, amount, continuing=self.autonomy)
        if reason:
            raise ValueError(reason)
        self.gesture_uses_head = False
        self.gesture_kind = 'motion'
        self.last_expression = dict(name=action, amount=amount, status='running')
        self.gesture = asyncio.create_task(self._motion(action, amount))
        return self.gesture

    async def _motion(self, action, amount):
        completed, error = False, None
        self.animation_name = 'motor action'
        try:
            await self.cancel_head()
            async with self.control_if_needed():
                await self.motors.perform(action, amount)
            completed = True
        except asyncio.CancelledError:
            error = 'Motion cancelled.'
            raise
        except (ValueError, RuntimeError) as exc:
            error = str(exc)
        except Exception:
            error = 'Robot motor action failed.'
        finally:
            self.animation_name = None
            self.last_expression = dict(name=action, amount=amount,
                status='completed' if completed else 'cancelled' if error == 'Motion cancelled.' else 'failed', error=error)
        return self.last_expression

    async def stop_motion(self):
        had_action = self.gesture and not self.gesture.done()
        await self.cancel_expression()
        await self.cancel_head()
        # Cancelling a supervised action stops its motors before releasing its
        # temporary lease. Do not seize idle autonomy simply to stop no action.
        return {'status': 'stopped' if had_action else 'idle', 'scope': 'Live-requested actions'}

    async def run(self):
        previous = None
        next_frame = 0
        started = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if self.gesture and not self.gesture.done() and (
                    (self.mode == 'off' and self.gesture_kind != 'motion') or getattr(self.robot, 'control_error', None)
                    or (self.gesture_uses_head and not self.safe_head())
                    or (self.animation_name in self.clips and not self.legacy_enabled)):
                    await self.cancel_expression()
                if not self.autonomy and self.legacy_enabled and self.mode != 'off' and not self.catalog_checked and not self.head and not self.player.clip and not (self.gesture and not self.gesture.done()):
                    await self.load_animations()
                if self.head and (self.head.done() or not self.safe_head()):
                    await self.cancel_head()
                if self.mode == 'off' or self.error or getattr(self.robot, 'control_error', None):
                    self.state = 'degraded' if self.error else 'off'
                    previous = None
                else:
                    state = ('speaking' if self.player.clip is not None else
                             'thinking' if self.session.backend_pending else 'listening')
                    self.state = state
                    if self.autonomy:
                        # Ordinary Vector owns face/head/wheels except during a
                        # requested SDK action; never repaint his native face.
                        previous = None
                        await asyncio.sleep(.1)
                        continue
                    if state == 'speaking' and previous != state and now-self.last_nod >= self.nod_interval and self.safe_head() and not self.head and not (self.gesture and not self.gesture.done()):
                        self.last_nod = now
                        self.head = asyncio.create_task(self.nod())
                    if self.animation_name:
                        previous = None
                        await asyncio.sleep(.1)
                        continue
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
            await self.cancel_expression()
            await self.cancel_head()
            # Pending actions stop before control release. Face images expire
            # in <=700ms; releasing SDK control restores ordinary eyes.

    async def close(self):
        self.closing = True
        await self.cancel_expression()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.cancel_head()
        self.state = 'off'
