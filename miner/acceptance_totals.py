"""Persistent local accepted-solution totals, never blockchain reward totals.

Only the seeker owns this writer. UI readers read the atomically published JSON.
The first use migrates exact event lines from live-gpu.log; telemetry snapshots
and protocol-test logs are intentionally not counted.
"""
import json
import os
from pathlib import Path
from status_io import write_status

EVENT_LINE='Verified GPU solution accepted; continuing same job'
SCHEMA_VERSION=1


def _count(value,label):
    if isinstance(value,bool) or not isinstance(value,int) or value<0:
        raise ValueError(label+' must be a nonnegative integer')
    return value


def _session(value):
    if not isinstance(value,str) or not value.strip() or len(value)>128:
        raise ValueError('session_id must be a nonempty string of at most 128 characters')
    return value


class _WriterLock:
    def __init__(self,path):
        self.file=None
        opened=Path(path).open('a+b')
        try:
            opened.seek(0,os.SEEK_END)
            if opened.tell()==0:
                opened.write(b'\0'); opened.flush()
            opened.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(opened.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(opened.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.file=opened
        except Exception as exc:
            opened.close()
            raise RuntimeError('Another miner is updating acceptance totals for this data folder.') from exc

    def close(self):
        if self.file is None: return
        opened=self.file; self.file=None
        try:
            opened.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(opened.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(opened.fileno(),fcntl.LOCK_UN)
        finally:
            opened.close()


def _state(value):
    if not isinstance(value,dict) or value.get('schema_version')!=SCHEMA_VERSION or isinstance(value.get('schema_version'),bool):
        raise ValueError('unsupported acceptance totals schema')
    migrated=_count(value.get('migrated_log_count'),'migrated_log_count')
    total=_count(value.get('total_accepted'),'total_accepted')
    sessions=value.get('session_counts')
    if not isinstance(sessions,dict): raise ValueError('session_counts must be an object')
    validated={_session(key):_count(count,'session count') for key,count in sessions.items()}
    if total!=migrated+sum(validated.values()): raise ValueError('acceptance totals do not match their session history')
    return {'schema_version':SCHEMA_VERSION,'total_accepted':total,
            'migrated_log_count':migrated,'session_counts':validated}


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate JSON key')
        result[key]=value
    return result


class AcceptanceTotals:
    def __init__(self,data_root,log_path=None):
        self.data_root=Path(data_root)
        self.path=self.data_root/'logs'/'acceptance-totals.json'
        self.log_path=Path(log_path) if log_path is not None else self.data_root/'logs'/'live-gpu.log'
        self.closed=False; self.persisted=False; self._lock=None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=_WriterLock(self.path.parent/'acceptance.lock')
        try:
            try:
                raw=self.path.read_text(encoding='utf-8')
            except FileNotFoundError:
                migrated=self._migrate_log()
                self._data={'schema_version':SCHEMA_VERSION,'total_accepted':migrated,
                            'migrated_log_count':migrated,'session_counts':{}}
                self._flush()
            else:
                try:
                    self._data=_state(json.loads(raw,object_pairs_hook=_unique_object))
                except (ValueError,TypeError) as exc:
                    raise RuntimeError('Acceptance totals file is corrupt or inconsistent. It was preserved; restore a valid backup before mining.') from exc
                self.persisted=True
        except Exception:
            self.closed=True; self._lock.close(); self._lock=None
            raise

    def _migrate_log(self):
        try:
            source=self.log_path.open('r',encoding='utf-8',errors='replace')
        except FileNotFoundError:
            return 0
        with source:
            return sum(line.strip()==EVENT_LINE for line in source)

    def _flush(self):
        # A false acknowledgement leaves the same in-memory state pending.
        self.persisted=False
        self.persisted=bool(write_status(self.path,self._data))
        return self.persisted

    @property
    def total_accepted(self): return self._data['total_accepted']

    @property
    def migrated_log_count(self): return self._data['migrated_log_count']

    def observe(self,session_id,count):
        if self.closed: raise RuntimeError('Acceptance totals writer is closed')
        session_id=_session(session_id); count=_count(count,'count')
        previous=self._data['session_counts'].get(session_id,0)
        if count<previous:
            raise ValueError('Accepted count decreased for the same session_id; use a new session ID after restart')
        is_new=session_id not in self._data['session_counts']
        if is_new or count>previous:
            self._data['session_counts'][session_id]=count
            self._data['total_accepted']+=count-previous
            self.persisted=False
        if not self.persisted:
            self._flush()
        return self.total_accepted

    def snapshot(self):
        return {'schema_version':SCHEMA_VERSION,'total_accepted':self.total_accepted,
                'migrated_log_count':self.migrated_log_count,'persisted':self.persisted,
                'session_count':len(self._data['session_counts'])}

    def close(self):
        if self.closed: return self.persisted
        try:
            if not self.persisted: self._flush()
            return self.persisted
        finally:
            self.closed=True
            if self._lock is not None:
                self._lock.close(); self._lock=None

    def __enter__(self): return self
    def __exit__(self,*args): self.close()
