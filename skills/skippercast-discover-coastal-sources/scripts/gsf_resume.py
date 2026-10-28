#!/usr/bin/env python3
"""Separate bounded GSF replay scanner; never source qualification or v2 acceptance."""
import argparse,contextlib,fcntl,gzip,hashlib,json,math,os,resource,signal,stat,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

METHOD='gsf-sequential-replay-v1'
HARD=dict(chunks=8,new_records=10000,pings=2000,beams=1000000,replay_records=280000,read_bytes=250000000,chunk_read_bytes=64000000,chunk_seconds=45)


def stamp(t):return datetime.fromtimestamp(t,timezone.utc).isoformat().replace('+00:00','Z')
def instant(s):
    v=datetime.fromisoformat(s.replace('Z','+00:00'))
    if v.tzinfo is None:raise ValueError('explicit UTC timezone required')
    return v.timestamp()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(p):
    if Path(p).stat().st_size>1000000:raise ValueError('metadata file cap')
    return json.loads(Path(p).read_text())
def hashfile(p,deadline,cap=128000000):
    p=Path(p)
    if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode) or p.stat().st_size>cap:raise ValueError('local regular file/byte cap')
    h=hashlib.sha256()
    with p.open('rb') as f:
        while True:
            if time.time()>=deadline:raise TimeoutError('fixed deadline reached during verification')
            b=f.read(65536)
            if not b:break
            h.update(b)
    return h.hexdigest()
def atomic(p,v,new=False):
    p=Path(p);tmp=p.with_name(p.name+'.tmp-'+str(os.getpid()))
    try:
        with tmp.open('x') as f:
            json.dump(v,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        if new:os.link(tmp,p);tmp.unlink()
        else:os.replace(tmp,p)
        fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
    finally:tmp.unlink(missing_ok=True)
@contextlib.contextmanager
def locked(p):
    with Path(str(p)+'.lock').open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('scanner checkpoint already locked')
        yield

def runtime(path,deadline):
    r=read(path)
    if r.get('schema')!='gsf-resume-reader-v1' or r.get('gsf_version')!='3.11' or r.get('source_revision')!='09f565bba30c2b9e1514891f428e1e649dee7ebc':raise ValueError('unrecognized pinned upstream reader')
    if hashfile(r['executable'],deadline)!=r['sha256'] or hashfile(Path(__file__).with_name('gsf_scan.c'),deadline)!=r['adapter_sha256']:raise ValueError('reader or adapter hash changed')
    if not Path(r['executable']).is_absolute() or not os.access(r['executable'],os.X_OK):raise ValueError('reader must be executable absolute local path')
    return r

def load(path,expected):
    raw=Path(path).read_bytes()
    if len(raw)>1000000 or hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('external checkpoint hash mismatch')
    s=json.loads(raw)
    if s.get('schema')!='gsf-replay-checkpoint-v1' or s['config_sha256']!=digest(s['config']):raise ValueError('checkpoint configuration integrity mismatch')
    if s['config']['method']!=METHOD:raise ValueError('scanner method changed')
    return s

def result(path,s):
    return dict(checkpoint=str(Path(path).resolve()),checkpoint_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),status=s['status'],cursor=s['cursor'],deadline_utc=s['config']['deadline_utc'],accounting=s['accounting'])

def initialize(path,sample,quality_receipt,reader,bbox,deadline,new_records=10000,chunks=8,replay_records=280000,read_bytes=250000000,chunk_read_bytes=16000000,chunk_seconds=45,pings=2000,beams=1000000):
    path=Path(path);sample=Path(sample).resolve();deadline=instant(deadline);start=time.time()
    if not start<deadline<=start+3600:raise ValueError('deadline must be fixed within the next hour')
    if len(bbox)!=4 or not all(math.isfinite(x) for x in bbox) or not(-180<=bbox[0]<bbox[2]<=180 and -90<=bbox[1]<bbox[3]<=90):raise ValueError('invalid assigned bbox')
    limits=dict(chunks=chunks,new_records=new_records,pings=pings,beams=beams,replay_records=replay_records,read_bytes=read_bytes,chunk_read_bytes=chunk_read_bytes,chunk_seconds=chunk_seconds)
    if any(type(v)is not int or v<1 or v>HARD[k] for k,v in limits.items()):raise ValueError('limits outside hard ceilings')
    with locked(path):
        if path.exists():raise ValueError('checkpoint exists; clock cannot renew')
        r=runtime(reader,deadline);q=read(quality_receipt);source=q['source_id'];a=q['sample'];binding=q['binding']
        expected=dict(source_id=source,source_metadata_sha256=q['source_metadata_sha256'],asset_url=a['url'],sample_sha256=a['sha256'],sample_request_id=a['request_id'])
        if not source or not a['url'].startswith('https://') or any(binding.get(k)!=v for k,v in expected.items()):raise ValueError('historical sample/source binding mismatch')
        sample_hash=hashfile(sample,deadline,64000000)
        if sample_hash!=a['sha256'] or sample.stat().st_size!=a['bytes']:raise ValueError('source sample replaced or size mismatch')
        native=path.with_name(path.name+'.native.gsf');owned=False
        try:
            with sample.open('rb') as f:magic=f.read(2)
            if magic==b'\x1f\x8b':
                if native.exists():raise ValueError('owned expanded path already exists; no overwrite')
                # Reuse the reviewed decompressor and its unchanged 128MB/200x caps.
                from formats import inflate
                inflate(sample,native,time.monotonic()+max(0,deadline-time.time()))
                owned=True
            else:native=sample
            native_hash=hashfile(native,deadline)
            c=dict(method=METHOD,start_utc=stamp(start),deadline_utc=stamp(deadline),bbox=list(bbox),limits=limits,
                source_id=source,sample_path=str(sample),sample_sha256=sample_hash,sample_bytes=sample.stat().st_size,
                source_quality_receipt=str(Path(quality_receipt).resolve()),source_quality_receipt_sha256=hashfile(quality_receipt,deadline,1000000),
                source_binding=binding,native_path=str(native.resolve()),native_sha256=native_hash,native_bytes=native.stat().st_size,native_owned=owned,
                reader_receipt=str(Path(reader).resolve()),reader_receipt_sha256=hashfile(reader,deadline,1000000),reader=r)
            s=dict(schema='gsf-replay-checkpoint-v1',config=c,config_sha256=digest(c),status='READY',last_clock=time.time(),cursor=0,chunks=[],accounting=dict(fread_charged_bytes=0,replay_charged_records=0,new_committed_records=0),accepted=False)
            atomic(path,s,new=True)
            return result(path,s)
        except BaseException:
            if owned:native.unlink(missing_ok=True)
            raise

def verify_inputs(s):
    c=s['config'];deadline=instant(c['deadline_utc'])
    if time.time()<s['last_clock']:raise ValueError('UTC clock rollback detected')
    for key,hkey,cap in [('sample_path','sample_sha256',64000000),('native_path','native_sha256',128000000),('source_quality_receipt','source_quality_receipt_sha256',1000000),('reader_receipt','reader_receipt_sha256',1000000)]:
        if hashfile(c[key],deadline,cap)!=c[hkey]:raise ValueError('pinned source/native/receipt changed')
    runtime(c['reader_receipt'],deadline)
    return deadline

def child_limits():
    resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824));resource.setrlimit(resource.RLIMIT_FSIZE,(1000000,1000000));resource.setrlimit(resource.RLIMIT_NOFILE,(48,48))

def step(path,expected):
    path=Path(path)
    with locked(path):
        s=load(path,expected);c=s['config'];limits=c['limits'];a=s['accounting'];deadline=instant(c['deadline_utc'])
        if s['status']!='READY':raise ValueError('terminal or pending checkpoint; unchanged failure retry prohibited')
        if time.time()<s['last_clock']:raise ValueError('UTC clock rollback detected')
        if time.time()>=deadline:raise TimeoutError('fixed deadline expired; finalize without further reads')
        if len(s['chunks'])>=limits['chunks'] or a['replay_charged_records']+s['cursor']>limits['replay_records']:raise ValueError('chunk or cumulative replay budget exhausted')
        reserved=min(limits['chunk_read_bytes'],limits['read_bytes']-a['fread_charged_bytes'])
        if reserved<=0:raise ValueError('cumulative fread-requested byte budget exhausted')
        verify_inputs(s)
        seconds=min(limits['chunk_seconds'],deadline-time.time())
        if seconds<=0:raise TimeoutError('deadline reached during verification')
        folder=path.with_name(path.name+'.chunks');folder.mkdir(exist_ok=True)
        n=len(s['chunks'])+1;out=folder/f'{n:03}.json';err=folder/f'{n:03}.stderr'
        chunk=dict(index=n,status='PENDING',cursor_start=s['cursor'],reserved_read_bytes=reserved,reserved_replay_records=s['cursor'],output_path=str(out.resolve()),start_utc=stamp(time.time()))
        s['chunks'].append(chunk);s['status']='PENDING';s['last_clock']=time.time();a['fread_charged_bytes']+=reserved;a['replay_charged_records']+=s['cursor'];atomic(path,s)
        argv=[c['reader']['executable'],c['native_path'],str(s['cursor']),str(limits['new_records']),str(limits['pings']),str(limits['beams']),str(reserved),*map(str,c['bbox']),str(min(deadline,time.time()+seconds))]
        process=None
        try:
            with out.open('x') as stdout,err.open('x') as stderr:
                process=subprocess.Popen(argv,stdout=stdout,stderr=stderr,start_new_session=True,preexec_fn=child_limits)
                process.wait(timeout=seconds)
            if process.returncode!=0:raise ValueError('reader failed; reservation retained, chunk not committed')
            data=read(out)
            if data.get('schema')!='gsf-resume-chunk-v1' or data.get('status')!='ok':raise ValueError('invalid reader chunk')
            nr=data['records'];replay=data['replayed_records'];charged=data['fread_requested_bytes']
            if not(type(nr)is int and 0<=nr<=limits['new_records'] and replay==s['cursor'] and data['cursor_start']==s['cursor'] and data['cursor_end']==s['cursor']+nr and type(charged)is int and 0<=charged<=reserved):raise ValueError('chunk accounting mismatch')
            if data['pings']>limits['pings'] or data['beams_scanned']>limits['beams'] or not 0<=data['valid_depth_count']<=data['finite_depth_count']<=data['beams_scanned']:raise ValueError('native count ceiling mismatch')
            if data['stop'] not in ('eof','record_limit','beam_limit','beam_limit_before_ping','ping_limit'):raise ValueError('unsupported scan stop')
            verify_inputs(s)
            chunk.update(status='COMMITTED',data=data,output_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
            a['fread_charged_bytes']-=reserved-charged;a['new_committed_records']+=nr;s['cursor']+=nr
            s['status']='EOF' if data['stop']=='eof' else 'READY' if nr else 'NO_PROGRESS'
            if s['status']=='READY' and len(s['chunks'])>=limits['chunks']:s['status']='CHUNK_LIMIT'
        except BaseException as exc:
            chunk.update(status='FAILED',error=type(exc).__name__+': '+str(exc)[:256]);s['status']='FAILED'
        finally:
            if process is not None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
            chunk['end_utc']=stamp(time.time());s['last_clock']=max(s['last_clock'],time.time());atomic(path,s)
        return result(path,s)

def finalize(path,expected):
    path=Path(path)
    with locked(path):
        s=load(path,expected)
        if s['status']=='FINALIZED':raise ValueError('already finalized')
        if s['status']=='PENDING':raise ValueError('pending owner process cleanup unverified; supervisor must confirm stop before separate recovery')
        for ch in s['chunks']:
            if ch['status']=='COMMITTED' and hashlib.sha256(Path(ch['output_path']).read_bytes()).hexdigest()!=ch['output_sha256']:raise ValueError('committed chunk output changed')
        committed=[x['data'] for x in s['chunks'] if x['status']=='COMMITTED']
        pings=sum(x['pings'] for x in committed);selected=sum(x['selected_navigation_pings'] for x in committed);valid=sum(x['valid_depth_count'] for x in committed)
        eof=s['status']=='EOF';hold=None if valid else ('scan_limit_before_first_ping' if not pings and not eof else 'eof_without_pings' if not pings else 'no_navigation_selected_pings_eof' if not selected and eof else 'no_navigation_selected_pings_partial_scan' if not selected else 'selected_pings_without_valid_depths')
        receipt=dict(schema='gsf-resumable-observation-v1',method=METHOD,accepted=False,source_qualification='unaccepted',habitat='unassessed',render='blocked',config=s['config'],config_sha256=s['config_sha256'],checkpoint_status=s['status'],complete_eof=eof,committed_records=s['cursor'],accounting=s['accounting'],chunks=s['chunks'],observations=dict(pings=pings,navigation_selected_pings=selected,valid_depths=valid,crs=None,vertical_datum=None,sounding_support=None,grid_resolution=None),scan_hold=hold,limitations=['Sequential replay restores upstream decoder state; replay contributes no duplicate observations.','Navigation numeric selection is not sounding coverage; unknown native datum remains unknown.','Failed or pending chunks contribute no observations and keep their full reserved budget.','Standalone observation receipt never auto-attaches as source qualification or mapping acceptance.','If complete_eof is false, all unscanned remainder stays unknown.'])
        output=path.with_name(path.name+'.receipt.json');atomic(output,receipt,new=True)
        c=s['config']
        if c['native_owned']:
            expected_native=path.with_name(path.name+'.native.gsf').resolve()
            if Path(c['native_path'])!=expected_native:raise ValueError('owned native cleanup path mismatch')
            expected_native.unlink(missing_ok=True)
        s['status']='FINALIZED';s['receipt_path']=str(output.resolve());s['receipt_sha256']=hashlib.sha256(output.read_bytes()).hexdigest();atomic(path,s)
        return result(path,s)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('checkpoint',type=Path);sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('init');p.add_argument('--sample',type=Path,required=True);p.add_argument('--quality-receipt',type=Path,required=True);p.add_argument('--reader',type=Path,required=True);p.add_argument('--bbox',type=float,nargs=4,required=True);p.add_argument('--deadline',required=True)
    for name,default in [('new_records',10000),('chunks',8),('replay_records',280000),('read_bytes',250000000),('chunk_read_bytes',16000000),('chunk_seconds',45),('pings',2000),('beams',1000000)]:p.add_argument('--'+name.replace('_','-'),type=int,default=default)
    for name in ('step','status','finalize'):
        p=sub.add_parser(name);p.add_argument('--expected-sha256',required=True)
    args=vars(parser.parse_args());path=args.pop('checkpoint');cmd=args.pop('cmd')
    if cmd=='init':answer=initialize(path,**args)
    elif cmd=='step':answer=step(path,args['expected_sha256'])
    elif cmd=='finalize':answer=finalize(path,args['expected_sha256'])
    else:
        with locked(path):answer=result(path,load(path,args['expected_sha256']))
    print(json.dumps(answer,sort_keys=True))
if __name__=='__main__':main()
