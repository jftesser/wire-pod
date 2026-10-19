"""Rebuild quiet native clips from the checked-out firmware animation archives.

Only procedural face/head keyframes survive. No audio, wheel, lift, event,
backpack-light or nested-animation keyframe can enter these Live clips.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tarfile
from legacy_animations import LEGACY_MAP, CANCEL_ANIMATION

ALLOWED_TRACKS = {'ProceduralFaceKeyFrame', 'HeadAngleKeyFrame'}


def merge_engine_manifest(existing, quiet):
    if not isinstance(existing, list) or any(not isinstance(item,dict) or 'name' not in item or 'length_ms' not in item for item in existing):
        raise ValueError('Invalid engine animation manifest.')
    additions=quiet['engine_manifest_entries']
    names={item['name'] for item in additions}
    return [item for item in existing if item['name'] not in names] + additions


def build(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    wanted = set(LEGACY_MAP.values())
    clips = {}
    for archive in sorted(source.glob('*.tar')):
        with tarfile.open(archive) as bundle:
            for member in bundle:
                name = Path(member.name).stem
                if name not in wanted:
                    continue
                raw = bundle.extractfile(member).read()
                frames = [copy.deepcopy(frame) for frame in json.loads(raw)[name] if frame['Name'] in ALLOWED_TRACKS]
                if not any(frame['Name'] == 'ProceduralFaceKeyFrame' for frame in frames):
                    raise ValueError('Legacy clip has no procedural face.')
                for frame in frames:
                    if frame['Name'] == 'HeadAngleKeyFrame':
                        frame['angle_deg'] = max(-22, min(45, frame['angle_deg']))
                        frame['angleVariability_deg'] = 0
                new_name = 'anim_vectorlive_' + next(key for key, value in LEGACY_MAP.items() if value == name)
                data = (json.dumps({new_name: frames}, separators=(',', ':'), sort_keys=True)+'\n').encode()
                (destination/(new_name+'.json')).write_bytes(data)
                clips[name] = dict(name=new_name, duration_ms=max(f['triggerTime_ms']+f.get('durationTime_ms',0) for f in frames),
                    source_name=name, source_archive=archive.name, source_sha256=hashlib.sha256(raw).hexdigest(),
                    sha256=hashlib.sha256(data).hexdigest(), tracks=sorted({f['Name'] for f in frames}))
    if wanted != clips.keys():
        raise ValueError('Missing legacy animation source.')
    # A tiny face-only action queued NOW preempts any still-running animation.
    first = json.loads((destination/'anim_vectorlive_happy.json').read_text())['anim_vectorlive_happy']
    frame = copy.deepcopy(next(f for f in first if f['Name']=='ProceduralFaceKeyFrame'))
    frame.update(triggerTime_ms=0, durationTime_ms=33)
    data = (json.dumps({CANCEL_ANIMATION:[frame]},separators=(',', ':'),sort_keys=True)+'\n').encode()
    (destination/(CANCEL_ANIMATION+'.json')).write_bytes(data)
    manifest = dict(version=1, allowed_tracks=sorted(ALLOWED_TRACKS),
        cancellation=dict(name=CANCEL_ANIMATION,sha256=hashlib.sha256(data).hexdigest()),
        expressions={key:clips[value] for key,value in LEGACY_MAP.items()},
        engine_manifest_entries=[{'name':clip['name'],'length_ms':clip['duration_ms']} for clip in clips.values()] + [{'name':CANCEL_ANIMATION,'length_ms':33}])
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).parent/'firmware/wire-os-victor/EXTERNALS/animation-assets/animations')
    parser.add_argument('--destination',type=Path,default=Path(__file__).parent/'legacy_assets')
    parser.add_argument('--engine-manifest',type=Path,help='Existing robot engine index; preserves original entries and adds quiet clips.')
    args=parser.parse_args()
    result=build(args.source,args.destination)
    if args.engine_manifest:
        merged=merge_engine_manifest(json.loads(args.engine_manifest.read_text()),result)
        (args.destination/'engine-anim-manifest.json').write_text(json.dumps(merged,separators=(',',':'))+'\n')
    print('Built',len(result['expressions']),'legacy expression choices plus the cancellation clip.')
