"""Finite SDK motions, supervised against fresh physical robot state."""
import asyncio
import contextlib
import math
import time

from vector_audio import p

PREVIEWS = {'armsUp': ('lift', 100), 'armsDown': ('lift', 0),
    'wave': ('wave', 0), 'rollForward': ('roll', 50), 'rollBack': ('roll', -25),
    'turnLeft': ('turn', 30), 'turnRight': ('turn', -30), 'stopMotion': ('stop', 0)}
DANGER = sum(p.RobotStatus.Value(name) for name in (
    'ROBOT_STATUS_IS_PICKED_UP', 'ROBOT_STATUS_IS_FALLING',
    'ROBOT_STATUS_CLIFF_DETECTED', 'ROBOT_STATUS_IS_BEING_HELD',
    'ROBOT_STATUS_IS_CARRYING_BLOCK', 'ROBOT_STATUS_IS_PICKING_OR_PLACING'))
CHARGER = p.ROBOT_STATUS_IS_ON_CHARGER | p.ROBOT_STATUS_IS_CHARGING
MOVING = p.ROBOT_STATUS_ARE_WHEELS_MOVING | p.ROBOT_STATUS_IS_PATHING


def validate_motion(action, amount):
    if type(amount) not in (int, float) or not math.isfinite(amount):
        raise ValueError('Motion amount must be a finite number.')
    valid = ((action in ('wave', 'stop') and amount == 0)
        or (action == 'lift' and 0 <= amount <= 100)
        or (action == 'roll' and -50 <= amount <= 100 and abs(amount) >= 10)
        or (action == 'turn' and 5 <= abs(amount) <= 90))
    if not valid:
        raise ValueError('Use lift 0–100 percent, wave/stop 0, roll -50..100 mm (at least 10 mm), or turn ±5..90 degrees.')


class RobotMotion:
    def __init__(self, owner):
        self.owner = owner
        self.active_tag = None
        self.action = None
        self.amount = 0
        self.started_at = None
        self.completed = 0

    def reason(self, action, amount, continuing=False):
        owner, state = self.owner, self.owner.observed
        if owner.motion == 'off':
            return 'Live motor actions are disabled in admin.'
        if action in ('roll', 'turn') and owner.motion != 'full':
            return 'Enable arms and wheels in admin first.'
        if getattr(owner.robot, 'control_error', None) or owner.closing:
            return 'Robot control is unavailable or closing.'
        if state is None or time.monotonic()-owner.observed_at > .5:
            return 'Fresh robot state is unavailable.'
        if state.status & DANGER:
            return 'Pickup, cliff, falling or carried-object state prevents motion.'
        if not continuing and (state.status & MOVING or abs(state.left_wheel_speed_mmps) > 1 or abs(state.right_wheel_speed_mmps) > 1):
            return 'Wait until Vector is stationary.'
        if not math.isfinite(state.lift_height_mm) or not 25 <= state.lift_height_mm <= 100:
            return 'Lift position is invalid.'
        if action in ('roll', 'turn'):
            if state.status & CHARGER:
                return 'Wheel actions are disabled on the charger.'
            if state.lift_height_mm > 45:
                return 'Lower the arms before rolling or turning.'
            prox = state.prox_data
            # The rear has no range sensor: reverse is deliberately <=50mm.
            # The firmware's own cliff protections remain active for SDK actions.
            if action == 'turn' or amount > 0:
                margin = 60 if continuing else 60 + (amount if action == 'roll' else 20)
                if prox.is_lift_in_fov or not (prox.unobstructed or (prox.found_object and prox.distance_mm > margin)):
                    return 'Forward range sensor does not establish enough clear space.'
            pose = state.pose
            if not all(math.isfinite(v) for v in (pose.x, pose.y, state.pose_angle_rad)):
                return 'Robot pose is invalid.'
        return None

    async def stop(self):
        if self.active_tag is not None:
            with contextlib.suppress(Exception):
                await self.owner.robot.stub.CancelActionByIdTag(p.CancelActionByIdTagRequest(id_tag=self.active_tag), timeout=.4)
        with contextlib.suppress(Exception):
            await self.owner.robot.stub.StopAllMotors(p.StopAllMotorsRequest(), timeout=.4)

    async def rpc(self, method, request, action, amount, timeout):
        self.active_tag = request.id_tag
        task = asyncio.ensure_future(method(request, timeout=timeout))
        completed = False
        try:
            deadline = time.monotonic()+timeout
            while not task.done():
                if self.reason(action, amount, continuing=True):
                    raise RuntimeError('Motion cancelled by robot state or admin settings.')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Motion exceeded its deadline.')
                await asyncio.wait({task}, timeout=.05)
            result = await task
            if result.result.code != 0:
                raise RuntimeError('Robot did not complete the motor action.')
            completed = True
        finally:
            if not completed:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await self.stop()
            self.active_tag = None

    async def perform(self, action, amount):
        validate_motion(action, amount)
        reason = self.reason(action, amount)
        if reason:
            raise ValueError(reason)
        self.action, self.amount, self.started_at = action, amount, time.monotonic()
        completed = False
        try:
            if action in ('lift', 'wave'):
                original = self.owner.observed.lift_height_mm
                targets = [32+amount*.6] if action == 'lift' else [70, 38, 70, original]
                for height in targets:
                    await self.rpc(self.owner.robot.stub.SetLiftHeight, p.SetLiftHeightRequest(
                        height_mm=height, max_speed_rad_per_sec=1.5, accel_rad_per_sec2=3,
                        duration_sec=.4, id_tag=self.owner.allocate_tag(), num_retries=0), action, amount, 2)
                    await asyncio.sleep(.12)
                    if self.reason(action, amount, continuing=True) or abs(self.owner.observed.lift_height_mm-height) > 6:
                        raise RuntimeError('Lift completion was not confirmed by fresh position data.')
            elif action == 'roll':
                before = self.owner.observed.pose
                start = (before.x, before.y)
                await self.rpc(self.owner.robot.stub.DriveStraight, p.DriveStraightRequest(
                    dist_mm=amount, speed_mmps=35, should_play_animation=False,
                    id_tag=self.owner.allocate_tag(), num_retries=0), action, amount, abs(amount)/35+1.5)
                await asyncio.sleep(.12)
                after = self.owner.observed.pose
                traveled = math.hypot(after.x-start[0], after.y-start[1])
                if self.reason(action, amount, continuing=True) or not abs(amount)*.6 <= traveled <= abs(amount)+30:
                    raise RuntimeError('Roll completion was not confirmed by fresh pose data.')
            elif action == 'turn':
                before = self.owner.observed.pose_angle_rad
                await self.rpc(self.owner.robot.stub.TurnInPlace, p.TurnInPlaceRequest(
                    angle_rad=math.radians(amount), speed_rad_per_sec=.6, accel_rad_per_sec2=1.2,
                    tol_rad=math.radians(3), is_absolute=False,
                    id_tag=self.owner.allocate_tag(), num_retries=0), action, amount, abs(math.radians(amount))/.6+1.5)
                await asyncio.sleep(.12)
                delta = math.degrees(math.atan2(math.sin(self.owner.observed.pose_angle_rad-before), math.cos(self.owner.observed.pose_angle_rad-before)))
                if self.reason(action, amount, continuing=True) or abs(delta-amount) > 12:
                    raise RuntimeError('Turn completion was not confirmed by fresh heading data.')
            self.completed += 1
            completed = True
        finally:
            if not completed:
                await self.stop()
            self.action = None
