"""Reservation-owned process/thread-local sealed byte capabilities, no mtime cache."""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
import uuid

_REQUIRED=fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL
_SECRET=object()
_REGISTRY={}
MAX_BYTES=64*1024*1024
CHUNK_BYTES=1024*1024
from .authority import SourceAuthority


def _fingerprint(st):
    return (st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)


def _open_relative(root,relative,authority):
    root=Path(os.path.abspath(root))
    if type(authority) is not SourceAuthority:raise ValueError('exact reserved source authority required')
    authority.check(root,relative)
    parts=Path(relative).parts
    if Path(relative).is_absolute() or not parts or any(p in ('..','.') for p in parts):
        raise ValueError('explicit confined relative original source required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    chain=[(os.fstat(fd).st_dev,os.fstat(fd).st_ino,os.fstat(fd).st_mode)]
    try:
        for part in root.parts[1:]:
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=next_fd
            chain.append((os.fstat(fd).st_dev,os.fstat(fd).st_ino,os.fstat(fd).st_mode))
        for part in parts[:-1]:
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=next_fd
            chain.append((os.fstat(fd).st_dev,os.fstat(fd).st_ino,os.fstat(fd).st_mode))
        source=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
        return source,fd,parts[-1],root.joinpath(*parts),chain
    except BaseException:
        os.close(fd);raise


class FinalizationReceipt:
    def __init__(self,secret,proof,container_checked):
        if secret is not _SECRET:raise ValueError('private finalization construction')
        self._proof=proof;self._closed_success=False;self._invalid=False
        self._container_checked=container_checked
    def payload(self):
        if not self._closed_success or self._invalid:
            raise ValueError('finalization proof unavailable before successful context close')
        return copy.deepcopy(dict(schema='coastal-sealed-finalization-v1',snapshot=self._proof,
                    container_checked=self._container_checked,origin_unchanged_observed=True,
                    capability_closed=True,scientific_acceptance=False))


class SealedSnapshot:
    def __init__(self,secret,fd,proof):
        if secret is not _SECRET:raise ValueError('private capability construction required')
        self._fd=fd;self._lock=threading.RLock();self._borrowers=0
        _REGISTRY[id(self)]={'object':self,'fd':fd,'proof':copy.deepcopy(proof),
                            'pid':os.getpid(),'thread':threading.get_ident(),'closed':False,'container_checked':False,'finalized':False,'receipt':None,'closing_pending':False}
    def _entry(self):
        entry=_REGISTRY.get(id(self))
        if not entry or entry['object'] is not self or entry['closed']:
            raise ValueError('inactive/unregistered snapshot capability')
        if entry['pid']!=os.getpid() or entry['thread']!=threading.get_ident():
            raise ValueError('snapshot belongs to another process/thread')
        if self._fd!=entry['fd']:raise ValueError('snapshot FD altered')
        try:
            st=os.fstat(entry['fd']);seals=fcntl.fcntl(entry['fd'],fcntl.F_GET_SEALS)
        except OSError as exc:raise ValueError('snapshot FD closed/reused') from exc
        proof=entry['proof']
        if ((st.st_dev,st.st_ino,st.st_size)!=tuple(proof['snapshot_dev_inode_size'])
            or not stat.S_ISREG(st.st_mode) or seals&_REQUIRED!=_REQUIRED):
            raise ValueError('snapshot identity/seals changed')
        return entry
    @property
    def provenance(self):
        with self._lock:return copy.deepcopy(self._entry()['proof'])
    @property
    def logical_filename(self):
        return self.provenance['logical_filename']
    @contextmanager
    def borrow(self):
        with self._lock:
            entry=self._entry()
            if entry['finalized'] or entry['closing_pending']:raise ValueError('snapshot finalized/closing; no further readers')
            self._borrowers+=1
            try:
                yield f"/proc/self/fd/{entry['fd']}"
                self._entry()
            finally:
                self._borrowers-=1
                if self._borrowers==0 and entry['closing_pending']:
                    try:
                        st=os.fstat(entry['fd'])
                        if (st.st_dev,st.st_ino,st.st_size)==tuple(entry['proof']['snapshot_dev_inode_size']):
                            os.close(entry['fd'])
                    except OSError:pass
                    _REGISTRY.pop(id(self),None)
    def _endpoint(self,path):
        entry=self._entry()
        if not self._borrowers or str(path)!=f"/proc/self/fd/{entry['fd']}":
            raise ValueError('only active borrowed endpoint permitted')
        return entry
    def authenticated_sha(self,path):
        return self._endpoint(path)['proof']['sha256']
    @contextmanager
    def _open_hdf_unchecked(self):
        # HDF5 sec2 cannot resolve anonymous memfd names on this runtime.
        # File-object VFD reads the SAME sealed inode through a readonly handle.
        import h5py
        with self.borrow() as endpoint:
            entry=self._endpoint(endpoint)
            fd=os.open(endpoint,os.O_RDONLY|os.O_CLOEXEC)
            st=os.fstat(fd)
            if (st.st_dev,st.st_ino,st.st_size)!=tuple(entry['proof']['snapshot_dev_inode_size']):
                os.close(fd);raise ValueError('HDF borrowed inode mismatch')
            with os.fdopen(fd,'rb') as stream:
                with h5py.File(stream,'r') as handle:
                    yield handle

    @contextmanager
    def open_hdf(self):
        with self.borrow() as endpoint:
            self.check_container(endpoint)
            with self._open_hdf_unchecked() as handle:
                yield handle

    def validate_origin(self):
        entry=self._entry();proof=entry['proof']
        st=os.fstat(entry['origin_fd'])
        if list(_fingerprint(st))!=proof['origin']['fd_after']:
            raise ValueError('origin mutated after capture')
        source,directory,_,_,chain= _open_relative(proof['origin']['root'],proof['origin']['relative_path'],entry['authority'])
        try:
            if [list(item) for item in chain]!=proof['origin']['directory_chain']:
                raise ValueError('origin ancestor directory replaced')
            if list(_fingerprint(os.fstat(source)))!=proof['origin']['fd_after']:
                raise ValueError('origin pathname replaced after capture')
            if (os.fstat(directory).st_dev,os.fstat(directory).st_ino)!=entry['origin_directory_identity']:
                raise ValueError('origin parent directory replaced')
        finally:os.close(source);os.close(directory)
        return True

    def finalize(self):
        with self._lock:
            entry=self._entry()
            if self._borrowers or entry['finalized']:raise ValueError('finalization requires completed borrowers')
            self.validate_origin()
            entry['finalized']=True
            receipt=FinalizationReceipt(_SECRET,copy.deepcopy(entry['proof']),entry['container_checked'])
            entry['receipt']=receipt
            return receipt

    @contextmanager
    def open_raster(self,driver='BAG'):
        if driver!='BAG' or not self.logical_filename.lower().endswith('.bag'):
            raise ValueError('explicit logical BAG transport only')
        import rasterio
        with self.borrow() as endpoint:
            self.check_container(endpoint)
            with rasterio.Env(GDAL_PAM_ENABLED='NO',GDAL_NUM_THREADS='2'):
                with rasterio.open(endpoint,driver='BAG') as dataset:
                    if dataset.driver!='BAG' or dataset.count!=2 or not dataset.crs:
                        raise ValueError('strict BAG driver/2bands/CRS required')
                    if any(name!=endpoint for name in dataset.files):
                        raise ValueError('unbound GDAL secondary source refused')
                    yield dataset

    def check_container(self,path):
        entry=self._endpoint(path)
        # Cached predicates concern a sealed inode, not mutable pathname/mtime.
        if entry['container_checked']:return
        fd=entry['fd'];magic=os.pread(fd,8,0)
        if magic[:4] in (b'II*\0',b'MM\0*',b'II+\0',b'MM\0+'):
            entry['container_checked']=True;return
        if magic!=b'\x89HDF\r\n\x1a\n':raise ValueError('native container signature unsupported')
        import h5py
        with self._open_hdf_unchecked() as file:
            if not isinstance(file.get('BAG_root',getlink=True),h5py.HardLink):
                raise ValueError('BAG_root must be local hard link')
            group=file['BAG_root']
            if not isinstance(group,h5py.Group):raise ValueError('BAG_root must be group')
            pending=[file];visited=set();total=0
            while pending:
                group=pending.pop();address=h5py.h5o.get_info(group.id).addr
                if address in visited:continue
                visited.add(address)
                for name in group:
                    total+=1
                    if total>1024:raise ValueError('BAG link cap')
                    if not isinstance(group.get(name,getlink=True),h5py.HardLink):
                        raise ValueError('BAG external/soft link refused')
                    item=group[name]
                    if isinstance(item,h5py.Group):pending.append(item)
                    elif isinstance(item,h5py.Dataset):
                        if item.is_virtual or item.external:raise ValueError('BAG virtual/external storage refused')
                    else:raise ValueError('BAG object unsupported')
            root=file['BAG_root']
            for name in ('elevation','uncertainty','metadata'):
                if name not in root or not isinstance(root[name],h5py.Dataset):
                    raise ValueError('BAG required datasets absent')
            if root['metadata'].size*root['metadata'].dtype.itemsize>1_000_000:
                raise ValueError('BAG metadata cap')
        entry['container_checked']=True
    def close(self):
        with self._lock:
            entry=self._entry()
            if self._borrowers:raise ValueError('cannot close borrowed snapshot')
            entry['closed']=True;os.close(entry['fd'])
            del _REGISTRY[id(self)]


@contextmanager
def authenticate(root,relative,expected_sha,expected_bytes,*,authority,max_bytes=MAX_BYTES,chunk_bytes=CHUNK_BYTES,checkpoint=None):
    """One original read/hash plus independent POST-SEAL destination hash."""
    if (not isinstance(expected_sha,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha)
        or type(max_bytes)!=int or not 0<max_bytes<=MAX_BYTES
        or type(expected_bytes)!=int or not 0<expected_bytes<=max_bytes
        or type(chunk_bytes)!=int or not 0<chunk_bytes<=CHUNK_BYTES):
        raise ValueError('bounded exact original identity required')
    if type(authority) is not SourceAuthority:raise ValueError('exact reserved source authority required')
    authority.check(root,relative,expected_sha,expected_bytes)
    src=directory=mem=-1;view=None;body_success=False
    try:
        src,directory,name,origin,chain=_open_relative(root,relative,authority)
        before=os.fstat(src)
        if not stat.S_ISREG(before.st_mode) or before.st_size!=expected_bytes:
            raise ValueError('source regular size mismatch')
        suffixes={name.lower()+s for s in ('.aux.xml','.msk','.ovr','.aux','.rrd')}
        suffixes.update(Path(name).stem.lower()+s for s in ('.aux','.aux.xml','.msk','.ovr','.rrd','.tfw','.tifw','.tiffw','.wld','.tab','.rpb','.imd','.rpc'))
        with os.scandir(directory) as siblings:
            for count,sibling in enumerate(siblings,1):
                if count>1024:raise ValueError('origin directory entry cap')
                if sibling.name.lower() in suffixes:raise ValueError('unbound original sidecar refused')
        mem=os.memfd_create('coastal-auth-v1',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
        h=hashlib.sha256();copied=0;read_calls=0
        while copied<expected_bytes:
            part=os.read(src,min(chunk_bytes,expected_bytes-copied));read_calls+=1
            if not part:raise ValueError('source truncated during copy')
            h.update(part);offset=0
            while offset<len(part):
                wrote=os.write(mem,part[offset:])
                if wrote<=0:raise ValueError('snapshot copy write made no progress')
                offset+=wrote
            copied+=len(part)
            if checkpoint is not None:checkpoint(copied)
        extra=os.read(src,1);read_calls+=1
        if extra:raise ValueError('source grew during copy')
        after=os.fstat(src);named=os.stat(name,dir_fd=directory,follow_symlinks=False)
        if _fingerprint(before)!=_fingerprint(after) or _fingerprint(after)!=_fingerprint(named):
            raise ValueError('source origin identity changed during copy')
        actual=h.hexdigest()
        if actual!=expected_sha:raise ValueError('sealed bytes do not match expected SHA')
        fcntl.fcntl(mem,fcntl.F_ADD_SEALS,_REQUIRED)
        st=os.fstat(mem)
        if st.st_size!=expected_bytes:raise ValueError('sealed snapshot size changed')
        if fcntl.fcntl(mem,fcntl.F_GET_SEALS)&_REQUIRED!=_REQUIRED:
            raise ValueError('full snapshot seals missing')
        snapshot_hash=hashlib.sha256();position=0
        while position<expected_bytes:
            data=os.pread(mem,min(chunk_bytes,expected_bytes-position),position)
            if not data:raise ValueError('sealed snapshot truncated')
            snapshot_hash.update(data);position+=len(data)
        if snapshot_hash.hexdigest()!=expected_sha:
            raise ValueError('post-seal snapshot bytes do not match expected SHA')
        proof={'schema':'coastal-sealed-snapshot-v1','sha256':actual,'bytes':copied,
               'origin':{'root':str(Path(os.path.abspath(root))),'relative_path':Path(relative).as_posix(),
                         'fd_before':list(_fingerprint(before)),'fd_after':list(_fingerprint(after)),
                         'directory_chain':[list(item) for item in chain]},
               'logical_source':authority.logical_source,'logical_filename':name,'snapshot_dev_inode_size':[st.st_dev,st.st_ino,st.st_size],
               'generation':uuid.uuid4().hex,'seals':_REQUIRED,'source_full_hash_passes':1,'sealed_snapshot_full_hash_passes':1,
               'total_full_hash_passes':2,'sealed_snapshot_bytes_hashed':position,
               'sealed_snapshot_sha256':snapshot_hash.hexdigest(),
               'source_bytes_read':copied,'source_read_calls':read_calls,'source_eof_probe_requested_bytes':1,'source_bytes_hashed':copied,'snapshot_bytes_written':copied,
               'maximum_transient_copy_chunk_bytes':chunk_bytes,'origin_still_immutable_claim':False}
        view=SealedSnapshot(_SECRET,mem,proof);mem=-1
        entry=_REGISTRY[id(view)];entry['origin_fd']=src;entry['authority']=authority
        ds=os.fstat(directory);entry['origin_directory_identity']=(ds.st_dev,ds.st_ino)
        yield view
        body_success=True
    finally:
        try:
            if view is not None and id(view) in _REGISTRY:
                entry=_REGISTRY[id(view)];receipt=entry['receipt']
                try:
                    if view._borrowers:raise ValueError('borrow escaped authentication context')
                    view.validate_origin()
                    view.close()
                    if receipt is not None:
                        receipt._closed_success=body_success
                        receipt._invalid=not body_success
                except BaseException:
                    if receipt is not None:receipt._invalid=True
                    if view._borrowers:
                        entry['closing_pending']=True
                    else:
                        _REGISTRY.pop(id(view),None)
                    # Never close an unrelated descriptor reused after external tampering.
                    try:
                        st=os.fstat(entry['fd'])
                        if not view._borrowers and (st.st_dev,st.st_ino,st.st_size)==tuple(entry['proof']['snapshot_dev_inode_size']):
                            os.close(entry['fd'])
                    except OSError:pass
                    raise
        finally:
            for fd in (src,directory,mem):
                if fd>=0:
                    try:os.close(fd)
                    except OSError:pass
