"""Package only manifest-listed standalone test files and verify extraction."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,zipfile,shutil
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--profile',choices=('m1','settings','preview'),default='preview');args=parser.parse_args()
source=ROOT/f'build/{args.profile}-package'
manifest=json.loads((source/'manifest.json').read_text())
dist=ROOT/'dist';dist.mkdir(exist_ok=True)
suffix={'m1':'M1-test','settings':'settings-preview','preview':'batch-preview'}[args.profile]
destination=dist/('Exanima-zh-CN-0.9.5.2.zip' if args.profile=='preview' else f'Exanima-zh-CN-0.9.5.2-{suffix}.zip')
names=sorted([*manifest,'manifest.json'])
assert all(n in ('winmm.dll','ExanimaZh.dll','manifest.json') or n.startswith('ExanimaZh/') for n in names)
assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n for n in names)
assert not any(n.lower().endswith(('.exe','.rpk','.pdb','.ttf')) for n in names)
for name,digest in manifest.items(): assert hashlib.sha256((source/name).read_bytes()).hexdigest()==digest
if args.profile=='preview':assert (source/'ExanimaZh/README.txt').read_bytes()==(ROOT/'release/README.txt').read_bytes()
if destination.exists():
    previous_hash=hashlib.sha256(destination.read_bytes()).hexdigest()
    previous=dist/(destination.stem+'-previous-'+previous_hash[:12]+'.zip')
    if not previous.exists():shutil.copy2(destination,previous)
    assert hashlib.sha256(previous.read_bytes()).hexdigest()==previous_hash
with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for name in names: archive.write(source/name,name)
digest=hashlib.sha256(destination.read_bytes()).hexdigest()
target=ROOT/'build/install-verification'/digest[:12];target.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert sorted(archive.namelist())==names
    for name in names:
        output=(target/name).resolve();assert output.is_relative_to(target.resolve())
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(archive.read(name))
for name,expected in manifest.items(): assert hashlib.sha256((target/name).read_bytes()).hexdigest()==expected
checksum=destination.with_name(destination.name+'.sha256')
checksum.write_text(digest+'  '+destination.name+'\n',encoding='ascii',newline='\n')
assert checksum.read_text(encoding='ascii').split()[0]==hashlib.sha256(destination.read_bytes()).hexdigest()
report={'zip':str(destination),'bytes':destination.stat().st_size,'sha256':digest,'files':names,
        'checksum_file':str(checksum),'clean_extraction_verified':True,'contains_game_exe_or_rpk':False,'visual_confirmation_pending':True}
(ROOT/f'build/{args.profile}-package-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
