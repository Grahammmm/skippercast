"""Exact source grant issued only by the fixed real reservation/lease validator."""
import copy,os,time
from pathlib import Path
_SECRET=object()
_ISSUED={}
class SourceAuthority:
    def __init__(self,secret,job,packet,request_path,output_path):
        if secret is not _SECRET:raise ValueError('reserved worker authority required')
        _ISSUED[id(self)]=dict(object=self,pid=os.getpid(),job=copy.deepcopy(job),packet=copy.deepcopy(packet),
                              request_path=str(request_path),output_path=str(output_path))
    def check(self,root,relative,sha=None,size=None):
        entry=_ISSUED.get(id(self))
        if not entry or entry['object'] is not self or entry['pid']!=os.getpid():
            raise ValueError('inactive or foreign source authority')
        job,packet=entry['job'],entry['packet'];source=packet['source']
        if (str(Path(os.path.abspath(root)))!=str(Path(os.path.abspath(job['source_root'])))
            or relative!=job['source_relative_path'] or (sha is not None and sha!=source['sha256'])
            or (size is not None and size!=source['bytes'])):
            raise ValueError('source root/path/SHA/size differs from real reserved authority')
        from skippercast.coastal.coordinator.authenticated import authorize_worker
        authorize_worker(job,entry['request_path'],entry['output_path'],now=time.time())
        return True
    @property
    def logical_source(self):
        entry=_ISSUED.get(id(self))
        if not entry or entry['object'] is not self or entry['pid']!=os.getpid():raise ValueError('inactive source authority')
        return copy.deepcopy(entry['packet']['source'])
    def close(self):
        _ISSUED.pop(id(self),None)
def bind_reserved_source(job,request_path,output_path,*,now=None):
    from skippercast.coastal.coordinator.authenticated import authorize_worker
    packet=authorize_worker(job,request_path,output_path,now=time.time() if now is None else now)
    source=packet['source']
    if (packet.get('source_root')!=job.get('source_root') or packet.get('source_relative_path')!=job.get('source_relative_path')
        or not isinstance(job.get('source_relative_path'),str)
        or Path(job['source_relative_path']).parts!=(job['source_relative_path'],)):
        raise ValueError('persisted exact minimal source root/leaf required')
    if not isinstance(source['path'],str):raise ValueError('typed exact source path required')
    return copy.deepcopy(packet),SourceAuthority(_SECRET,job,packet,request_path,output_path)
