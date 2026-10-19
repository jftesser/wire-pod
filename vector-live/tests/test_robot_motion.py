import asyncio
import contextlib
import math
import time
from types import SimpleNamespace as NS

import pytest

from conversation_behaviors import ConversationBehaviors
from robot_motion import DANGER, CHARGER, validate_motion
from vector_audio import p


def behavior(stub=None):
    owner = ConversationBehaviors(NS(control_error=None, stub=stub), NS(clip=None), NS(backend_pending=set()))
    owner.mode, owner.motion = 'head', 'full'
    owner.observe(NS(status=0, head_angle_rad=.3, lift_height_mm=32,
        left_wheel_speed_mmps=0, right_wheel_speed_mmps=0, pose_angle_rad=0,
        pose=NS(x=0,y=0), prox_data=NS(is_lift_in_fov=False, unobstructed=True, found_object=False,distance_mm=0)))
    return owner


@pytest.mark.parametrize('action,amount', [('roll',101),('roll',-51),('roll',0),('turn',91),('turn',-91),('turn',1),('lift',101),('lift',-1),('wave',1),('roll',True),('roll',float('nan')),('turn',float('inf')),('navigate',0)])
def test_arbitrary_unbounded_or_non_numeric_motion_is_rejected(action,amount):
    with pytest.raises(ValueError):validate_motion(action,amount)


def test_motor_permissions_charger_sensor_and_freshness_are_enforced():
    b=behavior();m=b.motors
    assert m.reason('roll',50) is None
    b.observed.status=CHARGER
    assert m.reason('roll',50) and m.reason('turn',30)
    assert m.reason('lift',100) is None
    b.observed.status=DANGER
    assert m.reason('lift',100) and m.reason('roll',50)
    b.observed.status=0;b.observed.lift_height_mm=70
    assert m.reason('roll',50)
    b.observed.lift_height_mm=32;b.observed.prox_data.unobstructed=False
    assert m.reason('roll',50) and m.reason('turn',30)
    assert m.reason('roll',-25) is None
    b.observed.prox_data.found_object=True;b.observed.prox_data.distance_mm=90
    assert m.reason('roll',50) # needs the requested distance plus clearance
    assert m.reason('roll',50,continuing=True) is None
    b.motion='arms';assert m.reason('turn',30)
    b.motion='off';assert m.reason('lift',100)
    b.motion='full';b.observed_at-=1;assert m.reason('lift',100)


def test_cliff_and_admin_disable_cancel_and_stop_pending_motor_action():
    async def check(disable):
        begun=asyncio.Event();stopped=[];cancelled=[]
        class Stub:
            async def DriveStraight(self,request,timeout):
                begun.set();await asyncio.sleep(10)
            async def CancelActionByIdTag(self,request,timeout):cancelled.append(request.id_tag)
            async def StopAllMotors(self,request,timeout):stopped.append(True)
        b=behavior(Stub())
        task=b.start_motion('roll',50)
        await begun.wait()
        if disable:b.motion='off'
        else:b.observed.status=p.ROBOT_STATUS_CLIFF_DETECTED
        result=await asyncio.wait_for(task,.8)
        assert result['status']=='failed' and cancelled and stopped
        assert b.motors.action is None
    for disable in (False,True):asyncio.run(check(disable))


def test_success_requires_measured_pose_not_only_sdk_completion():
    async def check(move):
        requests=[]
        class Stub:
            async def DriveStraight(self,request,timeout):
                requests.append(request)
                if move:b.observed.pose.x=50
                return NS(result=NS(code=0))
            async def StopAllMotors(self,request,timeout):pass
        b=behavior(Stub());result=await b.start_motion('roll',50)
        assert result['status']==('completed' if move else 'failed')
        assert requests[0].dist_mm==50 and requests[0].speed_mmps==35
        assert not requests[0].should_play_animation and requests[0].num_retries==0
    for move in (False,True):asyncio.run(check(move))


def test_wave_is_bounded_and_restores_lift_height():
    async def check():
        heights=[]
        class Stub:
            async def SetLiftHeight(self,request,timeout):
                heights.append(request.height_mm);b.observed.lift_height_mm=request.height_mm;b.observed_at=time.monotonic()
                return NS(result=NS(code=0))
        b=behavior(Stub());b.observed.lift_height_mm=40
        result=await b.start_motion('wave',0)
        assert result['status']=='completed' and heights==[70,38,70,40]
    asyncio.run(check())


def test_turn_uses_relative_angle_and_confirms_wrapped_heading():
    async def check():
        class Stub:
            async def TurnInPlace(self,request,timeout):
                assert not request.is_absolute and request.num_retries==0
                assert math.isclose(request.speed_rad_per_sec,.6,rel_tol=1e-6)
                b.observed.pose_angle_rad=math.radians(-160)
                return NS(result=NS(code=0))
        b=behavior(Stub());b.observed.pose_angle_rad=math.radians(170)
        assert (await b.start_motion('turn',30))['status']=='completed'
    asyncio.run(check())


def test_natural_mode_never_paints_idle_face_and_releases_control_after_motion():
    async def check(cancel):
        held=[];stops=[];begun=asyncio.Event()
        class Robot:
            control_error=None
            @contextlib.asynccontextmanager
            async def control(self):
                held.append('acquire')
                try:yield
                finally:held.append('release')
        class Stub:
            async def SetLiftHeight(self,request,timeout):
                assert held==['acquire'];begun.set()
                if cancel:await asyncio.sleep(10)
                b.observed.lift_height_mm=request.height_mm;b.observed_at=time.monotonic()
                return NS(result=NS(code=0))
            async def DisplayFaceImageRGB(self,*args,**kwargs):raise AssertionError('Natural idle must not paint the face')
            async def CancelActionByIdTag(self,*args,**kwargs):pass
            async def StopAllMotors(self,*args,**kwargs):
                assert held==['acquire'];stops.append(True)
        b=behavior(Stub());r=Robot();r.stub=b.robot.stub;b.robot=r;b.autonomy=True
        async def fresh():
            while True:b.observed_at=time.monotonic();await asyncio.sleep(.02)
        refresh=asyncio.create_task(fresh());b.task=asyncio.create_task(b.run())
        try:
            action=b.start_motion('lift',100)
            await asyncio.wait_for(begun.wait(),1.5)
            if cancel:await b.stop_motion()
            else:assert (await action)['status']=='completed'
            assert held==['acquire','release']
            assert bool(stops)==cancel
        finally:
            await b.close();refresh.cancel();await asyncio.gather(refresh,return_exceptions=True)
    for cancel in (False,True):asyncio.run(check(cancel))
