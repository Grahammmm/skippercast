"""Aggregate admission for cooperating bounded writers, never a filesystem quota."""
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
import re
from pathlib import Path
import stat
from .handoff.common import confined, digest
from .retention import MIB, MANAGED_OUTPUT_PROFILE, MANAGED_OUTPUT_LIMITS

PROFILE = MANAGED_OUTPUT_PROFILE
LIMITS = MANAGED_OUTPUT_LIMITS
TOTAL = 64*MIB
METADATA_MAX = 256*1024
# Atomic ledger replacement can retain the old and new copies simultaneously.
OVERHEAD = 2*METADATA_MAX
MAX_FILES = 512
COMPACT_PROFILE = 'coastal-managed-output-32-v1'
COMPACT_LIMITS = {'native':16*MIB,'mapping':2*MIB,'render':8*MIB,'control':6*MIB}
COMPACT_V2_PROFILE = 'coastal-managed-output-32-v2'
COMPACT_V2_LIMITS = {'native':16*MIB,'mapping':3*MIB,'render':7*MIB,'control':6*MIB}
COMPACT_V3_PROFILE = 'coastal-managed-output-32-v3'
COMPACT_V3_LIMITS = {'native':29*MIB//2,'mapping':3*MIB,'render':0,'control':29*MIB//2}

DISCOVERY_PROFILE = 'coastal-managed-discovery-1-v1'
DISCOVERY_LIMITS = {'native':0,'mapping':0,'render':0,'control':MIB}
PRIVATE_RENDER_PROFILE = 'coastal-managed-private-render-16-v1'
PRIVATE_RENDER_LIMITS = {'native':0,'mapping':0,'render':15*MIB,'control':MIB}
BROWSER_PROFILE = 'coastal-managed-browser-16-v1'
BROWSER_LIMITS = {'native':0,'mapping':0,'render':8*MIB,'control':8*MIB}

def declaration(prior_retained_bytes, cumulative_cap_bytes, *, profile=PROFILE):
    limits=(LIMITS if profile==PROFILE else COMPACT_LIMITS if profile==COMPACT_PROFILE
            else COMPACT_V2_LIMITS if profile==COMPACT_V2_PROFILE
            else COMPACT_V3_LIMITS if profile==COMPACT_V3_PROFILE
            else DISCOVERY_LIMITS if profile==DISCOVERY_PROFILE
            else PRIVATE_RENDER_LIMITS if profile==PRIVATE_RENDER_PROFILE
            else BROWSER_LIMITS if profile==BROWSER_PROFILE else None)
    if limits is None:raise ValueError('closed output profile required')
    total=sum(limits.values())
    if type(prior_retained_bytes) is not int or prior_retained_bytes < 0:
        raise ValueError('exact nonnegative prior retained carry required')
    if type(cumulative_cap_bytes) is not int or prior_retained_bytes+total > cumulative_cap_bytes:
        raise ValueError('new output allocation exceeds cumulative authority')
    return dict(profile=profile, limits=dict(limits), total_bytes=total,
                prior_retained_bytes=prior_retained_bytes,
                cumulative_cap_bytes=cumulative_cap_bytes)

PARTITION_PROFILE = 'coastal-managed-five-skill-65-v1'
def partition_declarations(prior_retained_bytes, cumulative_cap_bytes, mission_root):
    """Pure immutable admission barrier; no directories or output are created."""
    if not isinstance(mission_root,str):raise ValueError('absolute fixed partition root required')
    root=Path(mission_root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('absolute fixed partition root required')
    specs={'runtime':COMPACT_V3_PROFILE,'discovery':DISCOVERY_PROFILE,
           'render':PRIVATE_RENDER_PROFILE,'browser':BROWSER_PROFILE}
    total=65*MIB
    if type(prior_retained_bytes) is not int or prior_retained_bytes<0:
        raise ValueError('exact prior partition carry required')
    if type(cumulative_cap_bytes) is not int or prior_retained_bytes+total>cumulative_cap_bytes:
        raise ValueError('full sibling partition exceeds cumulative authority')
    children={}
    for name,profile in specs.items():
        size=sum(declaration(0,total,profile=profile)['limits'].values())
        children[name]={'output_root':str(root/name),
                       'output_retention':declaration(prior_retained_bytes+total-size,
                                                     cumulative_cap_bytes,profile=profile)}
    return dict(schema=PARTITION_PROFILE,mission_root=mission_root,
                prior_retained_bytes=prior_retained_bytes,
                cumulative_cap_bytes=cumulative_cap_bytes,total_bytes=total,
                children=children,refunds=False)

def validate_partition(grant):
    supplied=grant.get('output_partition')
    if not isinstance(supplied,dict) or supplied != partition_declarations(
            supplied.get('prior_retained_bytes'),supplied.get('cumulative_cap_bytes'),
            supplied.get('mission_root')):
        raise ValueError('complete immutable sibling partition required before writes')
    name=grant.get('output_partition_role')
    child=supplied['children'].get(name) if isinstance(name,str) else None
    if child is None or child['output_root']!=grant.get('output_root') or child['output_retention']!=grant.get('output_retention'):
        raise ValueError('exact disjoint sibling role/root/carry required')
    return supplied

def validate_output_plan(grant):
    supplied=grant.get('output_retention')
    if not isinstance(supplied,dict) or supplied != declaration(
            supplied.get('prior_retained_bytes'),supplied.get('cumulative_cap_bytes'),profile=supplied.get('profile')):
        raise ValueError('immutable managed output profile required')
    root=grant.get('output_root')
    if not isinstance(root,str) or not Path(root).is_absolute() or '..' in Path(root).parts:
        raise ValueError('immutable absolute output_root required')
    if supplied['profile'] in (DISCOVERY_PROFILE,PRIVATE_RENDER_PROFILE,BROWSER_PROFILE) or 'output_partition' in grant:
        validate_partition(grant)
    return supplied

def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def register_disjoint(path, registered, ancestors):
    """Admit one managed path unless it equals, contains or lies inside an earlier one.

    Same outcome as checking path.is_relative_to(other) or other.is_relative_to(path)
    against every earlier path, in O(depth) set lookups instead of O(n) Path
    comparisons, so a full ledger read stays linear in its entries."""
    parents=[parent for parent in path.parents if parent!=Path('.')]
    if path in registered or path in ancestors or any(parent in registered for parent in parents):
        raise ValueError('managed output paths overlap')
    registered.add(path)
    ancestors.update(parents)

class BoundedFile:
    """Sequential bytes only: no seek, truncate, fileno or bypassing file handle."""
    def __init__(self, stream, maximum):
        self._stream=stream
        self.maximum=maximum
        self.size=0
    def write(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('bytes required')
        if self.size+(data.nbytes if isinstance(data,memoryview) else len(data))>self.maximum:
            raise ValueError('managed file ceiling exceeded before write')
        count=self._stream.write(data)
        self.size+=count
        return count
    def read(self, *args):
        raise io.UnsupportedOperation('write-only bounded stream')
    def tell(self):
        return self.size
    def flush(self):
        self._stream.flush()

class ManagedOutputs:
    """Durable nonrefundable file ceilings; unmanaged growth detected at checkpoints.

    Control includes metadata, reviews, SQLite/WAL and logs. Only writes through
    writer()/write_bytes() receive aggregate prewrite enforcement. Libraries or
    subprocesses writing paths directly are NOT covered by this API.
    """
    def __init__(self, root, grant, grant_digest):
        supplied=validate_output_plan(grant)
        if digest(grant)!=grant_digest:
            raise ValueError('output grant digest changed')
        if Path(root).is_symlink():raise ValueError('owned output root required')
        self.root=Path(root).resolve(strict=True)
        if str(self.root)!=grant['output_root']:
            raise ValueError('grant output root changed; no fresh allowance')
        self.plan=json.loads(json.dumps(supplied))
        self.profile=self.plan['profile']
        self.limits=self.plan['limits']
        self.grant_digest=grant_digest
        self.path=self.root/'managed-output.json'
        self.lock_path=self.root/'managed-output.lock'

    @contextmanager
    def lock(self):
        if self.lock_path.is_symlink():raise ValueError('owned regular lock required')
        fd=os.open(self.lock_path, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd,'a+b') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                raise ValueError('owned single-link lock required')
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    @classmethod
    def create(cls, root, grant, grant_digest):
        instance=cls(root,grant,grant_digest)
        with instance.lock():
            if instance.path.exists() or instance.path.is_symlink():
                raise ValueError('managed output ledger exists; never reset')
            if any(p.name!='managed-output.lock' for p in instance.root.iterdir()):
                raise ValueError('fresh exclusive managed output root required')
            instance._save(dict(schema=instance.profile,grant_digest=grant_digest,
                                plan=instance.plan,files={}))
        return instance

    def _save(self,state):
        raw=(json.dumps(state,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(raw)>METADATA_MAX:raise ValueError('ledger metadata growth ceiling exceeded')
        temp=self.root/'managed-output.pending'
        # Preserve interrupted ledger bytes; do not overwrite unexplained evidence.
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,self.path)
        sync_directory(self.root)

    def _read(self):
        return self._read_disjoint()[0]

    def _read_disjoint(self):
        """Read and validate the ledger, returning (state, registered, ancestors).

        registered and ancestors are the O(depth) disjoint-path sets built while
        validating the ledger. They are valid only inside the lock hold that
        took this read and only until the ledger is mutated; pass them to
        _reserve_locked so a reservation checks its new path in O(depth) set
        lookups instead of an O(N) pairwise is_relative_to scan. Never keep them
        across a lock release.
        """
        if self.path.is_symlink() or self.path.stat().st_nlink!=1 or self.path.stat().st_size>METADATA_MAX:
            raise ValueError('bounded single-link ledger required')
        state=json.loads(self.path.read_text())
        if state.get('schema')!=self.profile or state.get('grant_digest')!=self.grant_digest or state.get('plan')!=self.plan:
            raise ValueError('managed output identity changed')
        files=state.get('files')
        if not isinstance(files,dict) or len(files)>MAX_FILES:
            raise ValueError('bounded file registry required')
        registered=set();ancestors=set()
        for name,e in files.items():
            self._target(name)
            register_disjoint(Path(name),registered,ancestors)
            if not isinstance(e,dict):raise ValueError('managed file reservation required')
            if e.get('role') not in LIMITS or type(e.get('bytes')) is not int or e['bytes']<0 or not isinstance(e.get('intent'),str) or not e['intent'] or e.get('state') not in ('reserved','complete','uncertain'):
                raise ValueError('managed file reservation changed')
            self.validate_finite_identity(name,e["intent"])
            if e.get('binding')!=digest(dict(path=name,role=e['role'],bytes=e['bytes'],intent=e['intent'])):
                raise ValueError('managed reservation binding changed; no refund')
            for field, maximum in (('updates',1024),('revisions',4)):
                if field in e and (type(e[field]) is not int or not 0<=e[field]<=maximum):
                    raise ValueError('finite mutable output counter changed')
        return state, registered, ancestors

    def validate_finite_identity(self,name,intent):
        """Compact-v3 finite registry identities, checked before entry/file creation."""
        if self.profile!=COMPACT_V3_PROFILE:return
        if (not isinstance(name,str) or len(name)>140
            or re.fullmatch(r"[A-Za-z0-9_./-]+",name) is None):
            raise ValueError("compact-v3 finite ASCII path ceiling exceeded")
        if not isinstance(intent,str) or not intent.isascii() or not 0<len(intent)<=151:
            raise ValueError("compact-v3 finite ASCII intent ceiling exceeded")

    def _target(self,name):
        if not isinstance(name,str) or len(name)>512:raise ValueError('bounded relative output path required')
        target=confined(self.root,name,existing=False)
        if target==self.root or target.name.startswith('managed-output.') or any(part.startswith('managed-output.') for part in Path(name).parts):
            raise ValueError('reserved ledger namespace')
        return target

    def _observe(self):
        """One walk of the on-disk tree, in walk order, for _charge().

        Holds (relative path, size) per regular file. It stops at the first
        entry the audit refuses or cannot lstat and records that error in its
        place, so _charge() raises exactly what the inline walk raised, at the
        same point. An observation is valid only inside the lock hold that took
        it and only until something other than the caller's own pending
        reservation changes; never keep one across a lock release or a write.
        """
        seen=[]
        for directory,dirs,files in os.walk(self.root,followlinks=False):
            for name in (*dirs,*files):
                p=Path(directory)/name
                try:info=p.lstat()
                except OSError as exc:
                    seen.append(exc);return seen
                if stat.S_ISLNK(info.st_mode) or (name in files and (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1)):
                    seen.append(ValueError('single-link regular managed tree required'));return seen
                if name in files:seen.append((p.relative_to(self.root).as_posix(),info.st_size))
        return seen

    def _audit(self,state):
        return self._charge(state,self._observe())

    def _charge(self,state,seen):
        """The ceiling audit of _audit() over an observation from _observe()."""
        charged={role:0 for role in self.limits};charged['control']=OVERHEAD
        for e in state['files'].values():charged[e['role']]+=e['bytes']
        observed=0;unknown=0
        for item in seen:
            if isinstance(item,BaseException):raise item
            rel,size=item;observed+=size
            if rel in state['files']:
                if size>state['files'][rel]['bytes']:raise ValueError('managed retained file exceeded ceiling')
            elif rel in ('managed-output.json','managed-output.pending'):
                if size>METADATA_MAX:raise ValueError('metadata retained ceiling exceeded')
            elif rel=='managed-output.lock':
                if size!=0:raise ValueError('lock retained ceiling exceeded')
            else:unknown+=size
        charged['control']+=unknown
        if any(charged[r]>self.limits[r] for r in self.limits) or sum(charged.values())>self.plan['total_bytes']:
            raise ValueError('aggregate managed output allowance exhausted')
        if self.plan['prior_retained_bytes']+sum(charged.values())>self.plan['cumulative_cap_bytes']:
            raise ValueError('cumulative retained carry exceeded')
        return dict(charged_bytes=sum(charged.values()),charged_by_role=charged,
                    observed_bytes=observed,unmanaged_control_bytes=unknown,
                    prior_retained_bytes=self.plan['prior_retained_bytes'],
                    prewrite_enforcement='managed writer API only',disk_quota=False,
                    physical_io_measured=False)

    def audit(self):
        with self.lock():return self._audit(self._read())

    def _admit(self,name,role,max_bytes,intent):
        """Argument checks reserve_file() makes before it takes the lock."""
        self.validate_finite_identity(name,intent)
        self._target(name)
        if role not in LIMITS or type(max_bytes) is not int or max_bytes<0 or not isinstance(intent,str) or not intent:
            raise ValueError('exact role, byte ceiling and intent required')

    def _reserve_locked(self,state,seen,name,*,registered,ancestors,role,max_bytes,intent):
        """reserve_file() body. The caller holds the lock and passes the state
        from its own _read() and a walk from _observe() taken in this lock hold
        after that state's last save, plus the disjoint-path sets from that same
        _read(). Returns (live ledger entry, saved).

        A new entry is charged twice over ONE walk: before it is added and
        after. Between the two nothing touches the tree, and the new path is
        refused above if anything exists there, so a second walk would see the
        same files classified the same way. Its path overlap is refused in
        O(depth) set lookups by register_disjoint, which also records the path
        in registered/ancestors so a second reservation in the same lock hold
        (write_checkpoint's temporary) sees it.
        """
        self._charge(state,seen)
        entry:dict=dict(role=role,bytes=max_bytes,intent=intent,state='reserved',
                        binding=digest(dict(path=name,role=role,bytes=max_bytes,intent=intent)))
        if name in state['files']:
            old=state['files'][name]
            if any(old[k]!=entry[k] for k in ('role','bytes','intent')):
                raise ValueError('managed file identity changed; no refund or new lease')
            return old,False
        if len(state['files'])>=MAX_FILES:raise ValueError('file registry exhausted')
        register_disjoint(Path(name),registered,ancestors)
        if self._target(name).exists():raise ValueError('unregistered existing file preserved')
        state['files'][name]=entry
        self._charge(state,seen)
        self._save(state)
        return entry,True

    def reserve_file(self,name,*,role,max_bytes,intent):
        self._admit(name,role,max_bytes,intent)
        with self.lock():
            state,registered,ancestors=self._read_disjoint()
            entry,_=self._reserve_locked(state,self._observe(),name,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=intent)
            return dict(entry)

    @contextmanager
    def writer(self,name,*,role,max_bytes,intent):
        # Reserve and publish under ONE lock hold with one ledger read. The
        # reservation's audit is the prepublication audit: only its own ledger
        # save (bounded by _save) happens between it and the open below.
        self._admit(name,role,max_bytes,intent)
        with self.lock():
            state,registered,ancestors=self._read_disjoint()
            entry,_=self._reserve_locked(state,self._observe(),name,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=intent)
            with self._publish_locked(state,entry,name,max_bytes) as stream:
                yield stream

    @contextmanager
    def _publish_locked(self,state,entry,name,max_bytes):
        target=self._target(name)
        if target.exists():raise ValueError('existing managed output preserved; verify reuse explicitly')
        target.parent.mkdir(parents=True,exist_ok=True)
        # Persist each new ancestor entry before publishing a managed file.
        parent=target.parent
        while parent!=self.root:
            sync_directory(parent.parent)
            parent=parent.parent
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                sync_directory(target.parent)
                bounded=BoundedFile(stream,max_bytes)
                yield bounded
                stream.flush();os.fsync(stream.fileno())
            entry.update(state='complete',actual_bytes=target.stat().st_size,
                         sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        except BaseException:
            entry['state']='uncertain'
            self._save(state)
            raise
        self._save(state)
        self._audit(state)

    def write_bytes(self,name,data,*,role,max_bytes,intent):
        if not isinstance(data,bytes):raise TypeError('bytes required')
        if len(data)>max_bytes:raise ValueError('managed file ceiling exceeded before admission')
        self._admit(name,role,max_bytes,intent)
        target=self._target(name)
        with self.lock():
            state,registered,ancestors=self._read_disjoint()
            e,_=self._reserve_locked(state,self._observe(),name,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=intent)
            if e['state']=='complete':
                if target.stat().st_size!=len(data) or e.get('actual_bytes')!=len(data) or e.get('sha256')!=hashlib.sha256(data).hexdigest() or hashlib.sha256(target.read_bytes()).hexdigest()!=e['sha256']:
                    raise ValueError('completed managed output bytes changed')
                return False
            with self._publish_locked(state,e,name,max_bytes) as stream:stream.write(data)
        return True

    def relative_path(self,path):
        path=Path(path)
        if path.is_absolute():
            if not path.is_relative_to(self.root):raise ValueError('output path escapes immutable root')
            path=path.relative_to(self.root)
        return path.as_posix()

    def write_json(self,name,value,*,role,max_bytes,intent,replace=False,max_revisions=4):
        name=self.relative_path(name)
        raw=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if not replace:return self.write_bytes(name,raw,role=role,max_bytes=max_bytes,intent=intent)
        if type(max_revisions) is not int or not 0<max_revisions<=4:
            raise ValueError('finite metadata revisions required')
        if len(raw)>max_bytes:raise ValueError('JSON ceiling exceeded before managed write')
        entry=self.reserve_file(name,role=role,max_bytes=max_bytes,intent=intent)
        if entry['state']!='complete':
            return self.write_bytes(name,raw,role=role,max_bytes=max_bytes,intent=intent)
        current=self._target(name);before=current.read_bytes()
        if len(before)!=entry.get('actual_bytes') or hashlib.sha256(before).hexdigest()!=entry.get('sha256'):
            raise ValueError('existing JSON bytes changed')
        if raw==before:return False
        revision=entry.get('revisions',0)+1
        if revision>max_revisions:raise ValueError('finite metadata revision allowance exhausted')
        history=f'.managed-revisions/{name}/{revision}.before'
        staged=f'.managed-revisions/{name}/{revision}.after'
        self.write_bytes(history,before,role=role,max_bytes=max_bytes,intent=digest([intent,revision,'before']))
        self.write_bytes(staged,raw,role=role,max_bytes=max_bytes,intent=digest([intent,revision,'after']))
        with self.lock():
            state=self._read();self._audit(state);latest=state['files'][name]
            if latest.get('sha256')!=entry.get('sha256') or latest.get('revisions',0)!=revision-1:
                raise ValueError('metadata publication fence changed; staged evidence preserved')
            os.replace(self._target(staged),current)
            sync_directory(current.parent)
            latest.update(actual_bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),revisions=revision)
            state['files'][staged]['published_to']=name
            self._save(state)
            self._audit(state)
        return True

    def write_npz(self,name,arrays,*,role,max_bytes,intent):
        import numpy as np
        name=self.relative_path(name)
        if not isinstance(arrays,dict) or not arrays or any(np.asarray(v).dtype.hasobject for v in arrays.values()):
            raise ValueError('nonobject bounded numeric arrays required')
        # Each byte of uncompressed array input must fit its admitted ceiling.
        if sum(np.asarray(v).nbytes for v in arrays.values())>max_bytes:
            raise ValueError('NPZ uncompressed payload exceeds admitted ceiling')
        with self.writer(name,role=role,max_bytes=max_bytes,intent=intent) as stream:
            np.savez_compressed(stream,**arrays)

    def write_geotiff(self,name,values,profile,*,role,max_bytes,intent,tags=None,description=None,mask=None,unit=None):
        import numpy as np
        from rasterio.io import MemoryFile
        name=self.relative_path(name)
        values=np.asarray(values)
        if (values.ndim!=2 or values.shape[0]>128 or values.shape[1]>128
                or values.dtype not in (np.dtype('float32'),np.dtype('uint8'))
                or profile.get('count')!=1 or profile.get('height')!=values.shape[0]
                or profile.get('width')!=values.shape[1] or profile.get('driver')!='GTiff'
                or np.dtype(profile.get('dtype'))!=values.dtype):
            raise ValueError('bounded single-band native raster required')
        if ((description is not None and (not isinstance(description,str) or len(description)>1024))
                or (unit is not None and (not isinstance(unit,str) or len(unit)>16))
                or len(json.dumps(tags or {},sort_keys=True).encode())>65536):
            raise ValueError('bounded raster tags required')
        self.reserve_file(name,role=role,max_bytes=max_bytes,intent=intent)
        import rasterio
        if mask is not None and (np.asarray(mask).shape!=values.shape or not np.isin(mask,[0,1]).all()):
            raise ValueError('exact boolean raster support mask required')
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), MemoryFile() as memory:
            with memory.open(**profile) as raster:
                raster.write(values,1)
                if mask is not None:raster.write_mask(np.asarray(mask,dtype='uint8')*255)
                if tags:raster.update_tags(**tags)
                if unit:raster.set_band_unit(1,unit)
                if description:raster.set_band_description(1,description)
            raw=memory.read()
        # No filesystem raster bytes were created before exact admission.
        return self.write_bytes(name,raw,role=role,max_bytes=max_bytes,intent=intent)

    def connect_sqlite(self,name,*,intent,max_db_bytes=MIB):
        """Page-bounded SQLite with DELETE journal, no disk temp or attachment.

        Fixed page size and no cache spill bound the single rollback journal to
        one page-image per database page plus header/sector margin. Journal
        allocation is conservatively1.25x DB. This is the managed SQLite route,
        not a cap over arbitrary VFS or outside connection writes.
        """
        import sqlite3
        name=self.relative_path(name)
        if type(max_db_bytes) is not int or max_db_bytes<4096 or max_db_bytes%4096:
            raise ValueError('whole SQLite4096-byte page ceiling required')
        journal_bytes=max_db_bytes*5//4
        self.reserve_file(name,role='control',max_bytes=max_db_bytes,intent=digest([intent,'database']))
        self.reserve_file(name+'-journal',role='control',max_bytes=journal_bytes,intent=digest([intent,'journal']))
        target=self._target(name);target.parent.mkdir(parents=True,exist_ok=True)
        parent=target.parent
        while parent!=self.root:
            sync_directory(parent.parent);parent=parent.parent
        connection=sqlite3.connect(target,isolation_level=None,timeout=10)
        try:
            if connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]!='delete':
                raise ValueError('DELETE journal required')
            connection.execute('PRAGMA page_size=4096')
            if connection.execute('PRAGMA page_size').fetchone()[0]!=4096:
                raise ValueError('SQLite page size changed')
            pages=max_db_bytes//4096
            if connection.execute(f'PRAGMA max_page_count={pages}').fetchone()[0]!=pages:
                raise ValueError('existing database exceeds page allowance')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA temp_store=MEMORY')
            connection.execute('PRAGMA cache_spill=OFF')
            connection.execute('PRAGMA cache_size=-2048')
            connection.enable_load_extension(False)
            immutable={'journal_mode','page_size','max_page_count','synchronous',
                       'temp_store','cache_spill','cache_size'}
            def authorize(action,arg1,arg2,database,trigger):
                if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):return sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_PRAGMA and str(arg1).lower() in immutable and arg2 is not None:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            connection.set_authorizer(authorize)
            sync_directory(target.parent)
            self.audit()
            return connection
        except BaseException:
            connection.close()
            raise

    def append_bytes(self,name,data,*,role,max_bytes,intent):
        """Append through the same immutable full ceiling; failed logs are held."""
        if not isinstance(data,bytes):raise TypeError('bytes required')
        name=self.relative_path(name)
        self._admit(name,role,max_bytes,intent)
        with self.lock():
            state,registered,ancestors=self._read_disjoint()
            entry,_=self._reserve_locked(state,self._observe(),name,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=intent)
            path=self._target(name);size=path.stat().st_size if path.exists() else 0
            if path.exists() and (entry['state']!='complete' or entry.get('actual_bytes')!=size
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=entry.get('sha256')):
                raise ValueError('log partial/changed bytes preserved')
            if size+len(data)>max_bytes:raise ValueError('append ceiling exceeded before write')
            path.parent.mkdir(parents=True,exist_ok=True)
            parent=path.parent
            while parent!=self.root:
                sync_directory(parent.parent);parent=parent.parent
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'ab') as stream:
                    sync_directory(path.parent)
                    bounded=BoundedFile(stream,max_bytes);bounded.size=size
                    bounded.write(data);stream.flush();os.fsync(stream.fileno())
                entry.update(state='complete',actual_bytes=size+len(data),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            except BaseException:
                entry['state']='uncertain';self._save(state);raise
            self._save(state);self._audit(state)

    def reference(self,name,contract):
        name=self.relative_path(name)
        with self.lock():
            state=self._read();self._audit(state);entry=state['files'].get(name)
            if not entry or entry['state']!='complete':
                raise ValueError('completed managed reference required')
            path=self._target(name)
            if path.stat().st_size!=entry['actual_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('managed reference bytes changed')
            return dict(path=name,bytes=entry['actual_bytes'],sha256=entry['sha256'],contract=contract)

    def write_checkpoint(self,name,value,*,role,max_bytes,intent,max_updates=1024,previous_sha256=None):
        """Bounded mutable NEW checkpoint; two full ceilings admitted once.

        Existing sealed receipts never use this API. Each replacement verifies
        its prior bytes and uses an exclusive temporary file. A leftover
        temporary or interrupted publication stops subsequent writes.
        """
        name=self.relative_path(name)
        if type(max_updates) is not int or not 1<=max_updates<=1024:
            raise ValueError('finite checkpoint update allowance required')
        raw=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(raw)>max_bytes:raise ValueError('checkpoint ceiling exceeded before write')
        self._admit(name,role,max_bytes,intent)
        temporary=f'.managed-checkpoints/{name}'
        temporary_intent=digest([intent,'checkpoint-temporary'])
        with self.lock():
            state,registered,ancestors=self._read_disjoint();seen=self._observe()
            entry,saved=self._reserve_locked(state,seen,name,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=intent)
            # Same order as two reserve_file() calls: the checkpoint is reserved
            # (and saved) before the temporary's arguments are checked. Walk
            # again only if that reservation saved the ledger.
            self._admit(temporary,role,max_bytes,temporary_intent)
            if saved:seen=self._observe()
            self._reserve_locked(state,seen,temporary,registered=registered,ancestors=ancestors,role=role,max_bytes=max_bytes,intent=temporary_intent)
            target=self._target(name);staged=self._target(temporary)
            updates=entry.get('updates',0)
            if updates>=max_updates:raise ValueError('finite checkpoint update allowance exhausted')
            if target.exists():
                prior=hashlib.sha256(target.read_bytes()).hexdigest()
                if entry['state']!='complete' or prior!=entry.get('sha256') or target.stat().st_size!=entry.get('actual_bytes'):
                    raise ValueError('checkpoint prior state changed or uncertain')
                if previous_sha256 is not None and previous_sha256!=prior:
                    raise ValueError('checkpoint prior hash fence changed')
            elif previous_sha256 is not None:raise ValueError('checkpoint prior absent')
            target.parent.mkdir(parents=True,exist_ok=True);staged.parent.mkdir(parents=True,exist_ok=True)
            for child in (target.parent,staged.parent):
                while child!=self.root:
                    sync_directory(child.parent);child=child.parent
            fd=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as stream:
                    sync_directory(staged.parent)
                    bounded=BoundedFile(stream,max_bytes);bounded.write(raw)
                    stream.flush();os.fsync(stream.fileno())
                os.replace(staged,target);sync_directory(target.parent)
                entry.update(state='complete',actual_bytes=len(raw),
                             sha256=hashlib.sha256(raw).hexdigest(),updates=updates+1)
                self._save(state)
            except BaseException:
                entry['state']='uncertain';self._save(state);raise
            self._audit(state)
