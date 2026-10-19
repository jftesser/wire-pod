import asyncio
import math
import time
from types import SimpleNamespace as NS

from conversation_behaviors import ConversationBehaviors, UNSAFE, FRAMES
from vector_audio import p


def state(**kwargs):
    return NS(status=0, head_angle_rad=.3, left_wheel_speed_mmps=0, right_wheel_speed_mmps=0, **kwargs)


def test_head_requires_fresh_stationary_safe_state_and_never_drives():
    behavior=ConversationBehaviors(NS(control_error=None), NS(clip=None), NS(backend_pending=set()))
    behavior.mode='head'
    assert not behavior.safe_head()
    behavior.observe(state())
    assert behavior.safe_head()
    for flag in (8,32,16384,32768,65536,128):
        behavior.observed.status=flag
        assert not behavior.safe_head()
    behavior.observed.status=0
    behavior.observed_at-=2
    assert not behavior.safe_head()
    behavior.observe(state())
    behavior.mode='eyes'
    assert not behavior.safe_head()
    behavior.mode='head';behavior.robot.control_error='lost'
    assert not behavior.safe_head()
    assert all(len(image)==184*96*2 for image in FRAMES.values())
    # Full black background and big-endian RGB565 green eyes.
    assert FRAMES['listening',False,False][:2]==b'\0\0'


def test_nod_is_relative_bounded_and_cancels_action_on_stop():
    async def check():
        commands=[];cancelled=[];begun=asyncio.Event()
        class Stub:
            async def SetHeadAngle(self, request, timeout):
                commands.append(request)
                if len(commands)==3:
                    begun.set();await asyncio.sleep(20)
                return NS(result=NS(code=0))
            async def CancelActionByIdTag(self, request, timeout):
                cancelled.append(request.id_tag)
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='head';behavior.observe(state())
        await behavior.nod()
        assert behavior.nods_completed==1
        assert math.isclose(commands[0].angle_rad,.3-math.radians(8),abs_tol=1e-6)
        assert math.isclose(commands[1].angle_rad,.3,abs_tol=1e-6)
        assert all(p.FIRST_SDK_TAG<=x.id_tag<=p.LAST_SDK_TAG and x.num_retries==0 for x in commands)
        behavior.head=asyncio.create_task(behavior.nod())
        await begun.wait()
        await asyncio.wait_for(behavior.close(),1)
        assert cancelled==[commands[-1].id_tag] and behavior.head is None
    asyncio.run(check())


def test_face_failure_is_optional_and_head_unsafe_update_cancels():
    async def check():
        class Stub:
            async def DisplayFaceImageRGB(self, request, timeout):
                raise RuntimeError('offline face failure')
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='eyes'
        await behavior.run()
        assert behavior.state=='degraded' and behavior.error
        await behavior.close()
    asyncio.run(check())


def test_pickup_or_disabled_expressions_cancel_pending_head_action_promptly():
    async def check(disable):
        begun=asyncio.Event();cancelled=asyncio.Event()
        class Stub:
            async def SetHeadAngle(self,request,timeout):
                begun.set();await asyncio.sleep(20)
            async def CancelActionByIdTag(self,request,timeout):
                cancelled.set()
            async def DisplayFaceImageRGB(self,request,timeout):
                assert request.duration_ms==700
                return NS()
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=object()),NS(backend_pending=set()))
        behavior.mode='head';behavior.observe(state())
        behavior.task=asyncio.create_task(behavior.run())
        await asyncio.wait_for(begun.wait(),1)
        if disable:behavior.mode='off'
        else:behavior.observed.status=8
        await asyncio.wait_for(cancelled.wait(),.5)
        await behavior.close()
        assert behavior.nods_completed==0
    for disable in (False,True):asyncio.run(check(disable))


def test_custom_nod_depth_clamps_travel_and_restores_observed_pose():
    async def check():
        requests=[]
        class Stub:
            async def SetHeadAngle(self,request,timeout):
                requests.append(request);return NS(result=NS(code=0))
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='head';behavior.nod_depth=20
        observed=state();observed.head_angle_rad=math.radians(-15);behavior.observe(observed)
        assert await behavior.nod()
        assert math.isclose(requests[0].angle_rad,math.radians(-22),abs_tol=1e-6)
        assert math.isclose(requests[1].angle_rad,math.radians(-15),abs_tol=1e-6)
        await behavior.close()
    asyncio.run(check())
