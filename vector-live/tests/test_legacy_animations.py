import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from conversation_behaviors import ConversationBehaviors
from legacy_animations import catalog, CANCEL_ANIMATION, MANIFEST_PATH, LEGACY_MAP
from vector_audio import p


def test_native_assets_have_only_silent_face_head_tracks_and_pinned_hashes():
    manifest=json.loads(MANIFEST_PATH.read_text())
    assert set(manifest['expressions'])==set(LEGACY_MAP)
    for clip in [*manifest['expressions'].values(),manifest['cancellation']]:
        path=MANIFEST_PATH.parent/(clip['name']+'.json')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==clip['sha256']
        frames=json.loads(path.read_text())[clip['name']]
        assert frames and {f['Name'] for f in frames} <= {'ProceduralFaceKeyFrame','HeadAngleKeyFrame'}
        assert any(f['Name']=='ProceduralFaceKeyFrame' for f in frames)
        for frame in frames:
            if frame['Name']=='HeadAngleKeyFrame':assert -22<=frame['angle_deg']<=45 and frame['angleVariability_deg']==0


@pytest.mark.parametrize('mode',['eyes','head'])
def test_native_clip_arbitrates_face_and_never_uses_wheel_or_lift_tracks(mode):
    async def check():
        begun=asyncio.Event();finish=asyncio.Event();requests=[];faces=[];probed=False
        class Stub:
            async def ListAnimations(self,request,timeout):
                return NS(animation_names=[p.Animation(name=n) for n in [CANCEL_ANIMATION,*[c['name'] for c in catalog().values()]]])
            async def PlayAnimation(self,request,timeout):
                nonlocal probed
                if not probed:
                    probed=True
                    assert request.ignore_body_track and request.ignore_head_track and request.ignore_lift_track
                    await asyncio.sleep(.002)
                    return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
                if request.animation.name==CANCEL_ANIMATION:
                    assert request.ignore_body_track and request.ignore_head_track and request.ignore_lift_track
                    return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
                requests.append(request);begun.set();await finish.wait()
                return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
            async def DisplayFaceImageRGB(self,request,timeout):faces.append(request)
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode=mode;behavior.legacy_enabled=True
        behavior.observe(NS(status=0,head_angle_rad=.3,left_wheel_speed_mmps=0,right_wheel_speed_mmps=0))
        behavior.clips={key:{**clip,'duration_ms':1} for key,clip in behavior.clips.items()}
        await behavior.load_animations()
        gesture=behavior.start_expression('happy')
        await begun.wait()
        behavior.task=asyncio.create_task(behavior.run())
        await asyncio.sleep(.12)
        assert not faces  # Default RGB eyes cannot overwrite the native clip.
        with pytest.raises(ValueError):behavior.start_expression('love')
        finish.set();result=await gesture
        assert result['status']=='completed'
        assert requests[0].animation.name=='anim_vectorlive_happy'
        assert requests[0].ignore_body_track and requests[0].ignore_lift_track
        assert requests[0].ignore_head_track == (mode=='eyes')
        await asyncio.sleep(.12)
        assert faces  # Automatic eyes resume when the native clip is finished.
        await behavior.close()
    asyncio.run(check())


def test_native_cancel_preempts_clip_and_stops_motors_on_pickup():
    async def check():
        begun=asyncio.Event();cancelled=asyncio.Event();stopped=asyncio.Event()
        class Stub:
            async def PlayAnimation(self,request,timeout):
                if request.animation.name==CANCEL_ANIMATION:
                    assert request.ignore_body_track and request.ignore_head_track and request.ignore_lift_track
                    cancelled.set();return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
                begun.set();await asyncio.sleep(20)
            async def StopAllMotors(self,request,timeout):stopped.set()
            async def DisplayFaceImageRGB(self,request,timeout):pass
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='head';behavior.legacy_enabled=True;behavior.available_animations={'happy'}
        state=NS(status=0,head_angle_rad=.3,left_wheel_speed_mmps=0,right_wheel_speed_mmps=0)
        behavior.observe(state)
        gesture=behavior.start_expression('happy')
        await begun.wait();behavior.task=asyncio.create_task(behavior.run())
        state.status=8
        await asyncio.wait_for(stopped.wait(),.7)
        assert cancelled.is_set() and gesture.cancelled()
        assert behavior.last_expression['status']=='cancelled'
        await behavior.close()
    asyncio.run(check())


def test_disabled_or_unknown_animations_never_fall_back_to_original_noisy_assets():
    async def check():
        behavior=ConversationBehaviors(NS(control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='eyes'
        for name in ('happy','../arbitrary','anim_pounce_success_03'):
            with pytest.raises(ValueError):behavior.start_expression(name)
        behavior.legacy_enabled=True
        with pytest.raises(ValueError):behavior.start_expression('happy')
        behavior.available_animations={'happy'}
        with pytest.raises(ValueError):behavior.start_expression('happy',8)
        await behavior.close()
    asyncio.run(check())


def test_failed_installation_marker_disables_native_choices():
    async def check():
        class Stub:
            async def PlayAnimation(self,request,timeout):return NS(result=0)
        behavior=ConversationBehaviors(NS(stub=Stub()),NS(clip=None),NS(backend_pending=set()))
        await behavior.load_animations()
        assert not behavior.available_animations and behavior.legacy_error
        await behavior.close()
    asyncio.run(check())


def test_false_sdk_complete_for_missing_clip_is_not_claimed_as_success():
    async def check():
        class Stub:
            async def PlayAnimation(self,request,timeout):return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.mode='eyes';behavior.legacy_enabled=True;behavior.available_animations={'happy'}
        result=await behavior.start_expression('happy')
        assert result['status']=='failed' and 'happy' not in behavior.available_animations
        await behavior.load_animations()
        assert not behavior.available_animations and behavior.legacy_error
        await behavior.close()
    asyncio.run(check())


def test_engine_index_merge_preserves_all_original_animation_entries():
    from build_legacy_assets import merge_engine_manifest
    quiet=json.loads(MANIFEST_PATH.read_text())
    originals=[{'name':'original_a','length_ms':111,'extra':'preserved'},{'name':'original_b','length_ms':222}]
    merged=merge_engine_manifest(originals,quiet)
    assert merged[:2]==originals
    assert {x['name'] for x in merged[2:]}=={x['name'] for x in quiet['engine_manifest_entries']}
    assert merge_engine_manifest(merged,quiet)==merged


def test_off_suppresses_probe_and_enabling_legacy_during_session_prepares_it():
    async def check():
        requests=[]
        class Stub:
            async def PlayAnimation(self,request,timeout):
                requests.append(request);await asyncio.sleep(.002)
                return NS(result=p.BEHAVIOR_COMPLETE_STATE,animation=NS(name=request.animation.name))
            async def DisplayFaceImageRGB(self,request,timeout):pass
        behavior=ConversationBehaviors(NS(stub=Stub(),control_error=None),NS(clip=None),NS(backend_pending=set()))
        behavior.clips={key:{**clip,'duration_ms':1} for key,clip in behavior.clips.items()}
        behavior.legacy_enabled=True
        behavior.task=asyncio.create_task(behavior.run())
        await asyncio.sleep(.12)
        assert not requests and not behavior.catalog_checked
        behavior.mode='eyes'
        for _ in range(130):
            if behavior.available_animations:break
            await asyncio.sleep(.01)
        assert behavior.available_animations and len(requests)==1
        assert requests[0].ignore_body_track and requests[0].ignore_head_track and requests[0].ignore_lift_track
        await behavior.close()
    asyncio.run(check())
