import asyncio
import json
import time
import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from host_controller import Controller
import host_controller as app


def options():
    return SimpleNamespace(microphone_name='Offline mic', audio_python=__file__,
        aec_delay_ms=200, wirepod='unused', serial='test', ssh_target='unused',
        remote_audio_socket='/private/socket', key_file='/unused/env', seconds=600, volume=80)


def test_profile_edits_are_pending_for_existing_session_and_survive_restart(tmp_path):
    from persona import profile_revision
    from voice_settings import save_settings,read_settings
    args=options();args.settings_file=str(tmp_path/'settings.json')
    save_settings(args.settings_file,{'volume':80,'personality':'Original personality','table_context':'Kēru'})
    controller=Controller(args,tmp_path)
    revision=profile_revision(controller.settings)
    controller.process=SimpleNamespace(pid=123,returncode=None)
    (tmp_path/'session.json').write_text(json.dumps(dict(pid=123,heartbeat=time.time(),phase='ready',ready=True,profile_revision=revision)))
    assert not controller.status()['profile_pending']
    save_settings(args.settings_file,{'personality':'Edited personality'})
    controller.settings=read_settings(args.settings_file)
    assert controller.status()['profile_pending']
    assert controller.status()['configured_options']['personality']=='Edited personality'
    restarted=Controller(args,tmp_path)
    assert not restarted.status()['profile_pending']
    assert restarted.settings['personality']=='Edited personality'


def test_controller_requires_matching_fresh_child_heartbeat(tmp_path):
    controller = Controller(options(), tmp_path)
    assert controller.status()['phase'] == 'off'
    controller.process = SimpleNamespace(pid=123, returncode=None)
    def write(pid=123, age=0):
        (tmp_path/'session.json').write_text(json.dumps(dict(pid=pid, heartbeat=time.time()-age,
            phase='ready', ready=True, microphone_active=True, speaking=False)))
    write(pid=321)
    assert not controller.status()['ready']
    write(age=8)
    assert not controller.status()['ready']
    write()
    assert controller.status()['ready'] and controller.status()['microphone_active']
    controller.stopping = True
    assert controller.status()['phase'] == 'stopping'
    assert not controller.status()['ready']
    controller.process.returncode = 1
    assert controller.status()['phase'] == 'error'
    assert not controller.status()['microphone_active']


def test_controller_start_is_explicit_idempotent_and_stops_gracefully(tmp_path, monkeypatch):
    async def check():
        calls = []
        class Process:
            pid, returncode = 456, None
            def __init__(self):
                self.stdout = asyncio.StreamReader()
                self.stdout.feed_eof()
            def send_signal(self, sig):
                calls.append(sig)
                self.returncode = 0
            async def wait(self):
                return self.returncode
        async def create(*args, **kwargs):
            calls.append(args)
            return Process()
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
        controller = Controller(options(), tmp_path)
        assert not calls  # constructor and status cannot open a paid session
        await controller.start()
        await controller.start()
        assert len(calls) == 1
        assert '--input-mode' in calls[0] and 'continuous' in calls[0]
        controller.request_stop()
        await controller.stop_task
        assert controller.process.returncode == 0
        assert not controller.stopping
        await controller.close()
        with pytest.raises(ValueError):
            await controller.start()
    asyncio.run(check())


def test_pi_controller_serves_local_socket_without_ssh_or_paid_child(monkeypatch):
    from aiohttp import ClientSession, UnixConnector
    async def forbidden(*args, **kwargs):
        raise AssertionError('Idle Pi controller must not spawn a process.')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    async def check():
        with tempfile.TemporaryDirectory(prefix='vpi-') as directory:
            path = Path(directory) / 'control.sock'
            args = options()
            args.input_source = 'vector-sdk'
            args.local_control_socket = str(path)
            args.settings_file = str(Path(directory)/'settings.json')
            task = asyncio.create_task(app.serve(args))
            try:
                for _ in range(100):
                    if path.exists() or task.done():
                        break
                    await asyncio.sleep(.01)
                assert not task.done()
                assert path.stat().st_mode & 0o777 == 0o600
                async with ClientSession(connector=UnixConnector(path=str(path))) as client:
                    async with client.get('http://localhost/status') as response:
                        state = await response.json()
                        assert state['continuous_available'] and not state['active']
                        assert state['controller_location'] == 'Pi'
                        assert state['source'].startswith('Vector internal')
                        assert state['configured_volume']==80 and state['volume_available']
                    for value in (0,100,80):
                        async with client.post('http://localhost/volume',json={'volume':value}) as response:
                            assert response.status==200
                            assert (await response.json())['saved']
                    async with client.post('http://localhost/options',json={'boost_db':6,'expressions':'head','nod_depth':16,'nod_interval':4,'legacy_animations':True}) as response:
                        assert response.status==200
                    restored=Controller(args,directory)
                    assert restored.volume==80
                    assert restored.settings['boost_db']==6 and restored.settings['expressions']=='head'
                    assert restored.settings['nod_depth']==16 and restored.settings['nod_interval']==4 and restored.settings['legacy_animations']
                    async with client.post('http://localhost/expression',json={'expression':'happy','depth_degrees':0}) as response:
                        assert response.status==409
                    assert not restored.status()['active']
                    for body in ({'volume':True},{'volume':101},{'volume':2.5},{'volume':50,'mode':'continuous'}):
                        async with client.post('http://localhost/volume',json=body) as response:
                            assert response.status==409
                    async with client.post('http://localhost/start', json={'mode':'wrong'}) as response:
                        assert response.status == 409
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            assert not path.exists()
    asyncio.run(check())


def test_expression_preview_forwards_only_to_ready_matching_child_socket(tmp_path):
    from aiohttp import web
    async def check():
        with tempfile.TemporaryDirectory(prefix='vexpr-',dir='/tmp') as directory:
            controller=Controller(options(),directory)
            path=Path(directory)
            received=[]
            async def expression(request):
                received.append(await request.json())
                return web.json_response({'status':'accepted'},status=202)
            child=web.Application();child.router.add_post('/expression',expression)
            runner=web.AppRunner(child);await runner.setup()
            await web.UnixSite(runner,str(controller.expression_socket)).start()
            class Request:
                path='/expression';method='POST';content_type='application/json'
                async def json(self):return {'expression':'happy','depth_degrees':0}
            try:
                assert (await controller.handle(Request())).status==409
                controller.process=SimpleNamespace(pid=456,returncode=None)
                controller.status_path.write_text(json.dumps(dict(pid=455,heartbeat=time.time(),ready=True,phase='ready')))
                assert (await controller.handle(Request())).status==409
                controller.status_path.write_text(json.dumps(dict(pid=456,heartbeat=time.time(),ready=True,phase='ready')))
                assert (await controller.handle(Request())).status==202
                assert received==[{'expression':'happy','depth_degrees':0}]
            finally:await runner.cleanup()
    asyncio.run(check())
