"""Independent retained-output admission ledger; source volume is never refunded."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import os
import stat

from .handoff.common import confined, digest, write

MIB = 1024*1024
LIMITS = {'native':32*MIB,'mapping':8*MIB,'render':20*MIB,'discovery':MIB,'control':3*MIB}
TOTAL = 64*MIB
NATIVE_SLOTS = {f'native-{window}-{stage}' for window in 'ABCD' for stage in ('acquire','qualify')}


class Retention:
    """Reserve exact stage output ceilings before a writer is admitted.

    Unknown/interrupted reservations retain their entire ceilings. Observation
    checks enforce the owned file tree at stage boundaries; this is not a disk
    quota and cannot measure writes between checkpoints.
    """
    def __init__(self,root,plan_digest):
        self.root=Path(root).resolve(strict=True)
        self.path=self.root/'retention.json'
        self.plan_digest=plan_digest

    @classmethod
    def create(cls,root,plan_digest):
        instance=cls(root,plan_digest)
        with instance.lock():
            if instance.path.exists():raise ValueError('retention ledger exists; never reset')
            write(instance.path,dict(schema='coastal-retention-v1',plan_digest=plan_digest,
                limits=LIMITS,limits_sha256=digest(LIMITS),total_bytes=TOTAL,reservations={}))
        return instance

    @contextmanager
    def lock(self):
        with (self.root/'retention.lock').open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            yield

    def read(self):
        state=json.loads(self.path.read_text())
        if (state.get('schema')!='coastal-retention-v1' or state.get('plan_digest')!=self.plan_digest
                or state.get('limits')!=LIMITS or state.get('limits_sha256')!=digest(LIMITS)
                or state.get('total_bytes')!=TOTAL or not isinstance(state.get('reservations'),dict)):
            raise ValueError('immutable retention plan/limits changed')
        totals=dict.fromkeys(LIMITS,0)
        paths=[]
        for slot,entry in state['reservations'].items():
            role=entry.get('role')
            expected=4*MIB if slot in NATIVE_SLOTS and role=='native' else LIMITS.get(role) if slot==role and role in ('mapping','render','discovery') else None
            if (expected is None or type(entry.get('bytes')) is not int or entry['bytes']!=expected
                    or entry.get('state') not in ('reserved','complete','uncertain')
                    or not isinstance(entry.get('intent_digest'),str) or not entry['intent_digest']):
                raise ValueError('finite output reservation identity/cap changed')
            path=Path(entry.get('directory',''))
            if path.is_absolute() or '..' in path.parts or path.as_posix()=='.':
                raise ValueError('confined output reservation directory required')
            if any(path.is_relative_to(other) or other.is_relative_to(path) for other in paths):
                raise ValueError('output reservations overlap')
            paths.append(path);totals[role]+=expected
        if any(totals[role]>LIMITS[role] for role in totals):
            raise ValueError('retained-output reservations exceed immutable role cap')
        return state

    def reserve(self,slot,intent_digest,directory,*,role):
        if role=='native':
            if slot not in NATIVE_SLOTS:raise ValueError('eight finite native output slots only')
            amount=4*MIB
        elif role in ('mapping','render','discovery'):
            if slot!=role:raise ValueError('one finite stage output slot only')
            amount=LIMITS[role]
        else:raise ValueError('control files are observed in the3MiB remainder')
        target=confined(self.root,directory,existing=False)
        relative=target.relative_to(self.root).as_posix()
        if relative=='.':raise ValueError('exclusive task-owned subdirectory required')
        with self.lock():
            state=self.read()
            entry=dict(role=role,directory=relative,intent_digest=intent_digest,bytes=amount,state='reserved')
            if slot in state['reservations']:
                prior=state['reservations'][slot]
                if any(prior[key]!=entry[key] for key in ('role','directory','intent_digest','bytes')):
                    raise ValueError('output slot identity changed; no new lease allowance')
                return prior
            for prior in state['reservations'].values():
                other=Path(prior['directory'])
                if Path(relative).is_relative_to(other) or other.is_relative_to(relative):
                    raise ValueError('output reservations overlap')
            reserved=sum(x['bytes'] for x in state['reservations'].values() if x['role']==role)
            if reserved+amount>LIMITS[role]:raise ValueError('role retained-output allowance exhausted')
            state['reservations'][slot]=entry
            write(self.path,state)
            return entry

    def audit(self):
        with self.lock():
            state=self.read()
            observed={slot:0 for slot in state['reservations']}
            control=0
            for directory,dirs,files in os.walk(self.root,followlinks=False):
                for name in (*dirs,*files):
                    path=Path(directory)/name
                    kind=path.lstat()
                    if stat.S_ISLNK(kind.st_mode) or (name in files and (not stat.S_ISREG(kind.st_mode) or kind.st_nlink!=1)):
                        raise ValueError('single-link regular owned outputs required')
                    if name not in files:continue
                    relative=path.relative_to(self.root)
                    slots=[slot for slot,entry in state['reservations'].items()
                           if relative.is_relative_to(Path(entry['directory']))]
                    if len(slots)>1:raise ValueError('output belongs to overlapping reservations')
                    if slots:observed[slots[0]]+=kind.st_size
                    else:control+=kind.st_size
            if control>LIMITS['control']:raise ValueError('control retained-output allowance exceeded')
            for slot,value in observed.items():
                if value>state['reservations'][slot]['bytes']:
                    raise ValueError('reserved stage retained-output ceiling exceeded')
            total=control+sum(observed.values())
            if total>TOTAL:raise ValueError('aggregate retained-output ceiling exceeded')
            return dict(observed_bytes=total,control_bytes=control,slots=observed,
                        reserved_bytes=sum(x['bytes'] for x in state['reservations'].values()),
                        source_volume_accounted=False,physical_io_measured=False,disk_quota=False)

    def settle(self,slot,*,completed):
        if type(completed) is not bool:
            raise ValueError('completed must be a bool')
        before=self.audit()
        with self.lock():
            state=self.read();entry=state['reservations'][slot]
            entry['state']='complete' if completed else 'uncertain'
            entry['observed_bytes']=before['slots'][slot]
            # Reservation is never returned; a new directory/intent needs new authority.
            write(self.path,state)
        return before

# New opt-in managed writer profile; legacy observation-only profile stays unchanged.
MANAGED_OUTPUT_PROFILE = 'coastal-managed-output-64-v1'
MANAGED_OUTPUT_LIMITS = {'native':32*MIB,'mapping':8*MIB,'render':8*MIB,'control':16*MIB}
