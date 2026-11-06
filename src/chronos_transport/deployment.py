"""Installation profiles and durable request allowance. No network or credentials.

Wired into the optional local guard profile. A profile is configuration, not
permission to spend money or send data. Remote execution remains disabled until
an explicit opt-in and verified transport implementation exist.
"""
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3
import time


class DeploymentError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)


@dataclass(frozen=True)
class Profile:
    deployment_id: str
    provider: str
    model: str
    schema_sha256: str
    request_limit: int
    local_port: int | None
    version: int = 1
    reasoning_effort: str = 'none'
    response_contract: str = 'chronos.agent-proposal.v2'

    def __post_init__(self):
        if (type(self.version) is not int or self.version not in (1,2,3,4,5,6)
                or type(self.reasoning_effort) is not str or self.reasoning_effort not in ('none','low','medium')
                or (self.version==1 and self.reasoning_effort!='none')
                or type(self.response_contract) is not str
                or self.response_contract != ({3:'chronos.preference-extraction.v1',4:'chronos.case-conversation.v1',5:'chronos.case-explanation-plan.v1',6:'chronos.case-explanation-plan.v2'}.get(self.version,'chronos.agent-proposal.v2'))
                or (self.version in (4,5,6) and self.provider!='ollama')):
            raise DeploymentError('INVALID_REASONING_PROFILE')

    @classmethod
    def parse(cls,raw):
        if not isinstance(raw,(str,bytes)) or len(raw)>4096:raise DeploymentError('INVALID_PROFILE')
        def pairs(items):
            out={}
            for key,value in items:
                if key in out:raise DeploymentError('DUPLICATE_PROFILE_FIELD')
                out[key]=value
            return out
        def invalid_constant(_):raise DeploymentError('INVALID_PROFILE')
        try:
            data=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid_constant)
        except (ValueError,UnicodeError,RecursionError):raise DeploymentError('INVALID_PROFILE') from None
        fields={'version','deployment_id','provider','model','schema_sha256','request_limit','local_port'}
        if type(data) is not dict:raise DeploymentError('INVALID_PROFILE_FIELDS')
        version=data.get('version')
        if type(version) is not int or version not in (1,2,3,4,5,6):raise DeploymentError('INVALID_PROFILE_VERSION')
        if version>=2:fields.add('reasoning_effort')
        if version>=3:fields.add('response_contract')
        if set(data)!=fields:raise DeploymentError('INVALID_PROFILE_FIELDS')
        if type(data['deployment_id']) is not str or not re.fullmatch(r'[a-f0-9]{32}',data['deployment_id']):raise DeploymentError('INVALID_DEPLOYMENT_ID')
        if data['provider'] not in ('ollama','openai-chat-json'):raise DeploymentError('UNSUPPORTED_PROVIDER')
        if type(data['model']) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',data['model']):raise DeploymentError('INVALID_MODEL')
        if type(data['schema_sha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}',data['schema_sha256']):raise DeploymentError('INVALID_SCHEMA_DIGEST')
        if type(data['request_limit']) is not int or not 1<=data['request_limit']<=1000:raise DeploymentError('INVALID_REQUEST_LIMIT')
        port=data['local_port']
        if data['provider']=='ollama':
            if type(port) is not int or not 1024<=port<=65535:raise DeploymentError('INVALID_LOCAL_PORT')
        elif port is not None:raise DeploymentError('REMOTE_PORT_FIXED')
        return cls(**{k:data[k] for k in fields})

    def public(self):
        value={'version':self.version,'deployment_id':self.deployment_id,'provider':self.provider,
                'model':self.model,'schema_sha256':self.schema_sha256,
                'request_limit':self.request_limit,'local_port':self.local_port}
        if self.version>=2:value['reasoning_effort']=self.reasoning_effort
        if self.version>=3:value['response_contract']=self.response_contract
        return value

    @property
    def digest(self):return sha256(_canonical(self.public()).encode()).hexdigest()

    @property
    def endpoint(self):
        return f'http://127.0.0.1:{self.local_port}/v1/chat/completions' if self.provider=='ollama' else 'https://api.openai.com/v1/chat/completions'


class Allowance:
    """One immutable installation budget; claim and count commit together.

    No auto-creation on open, expiry refund, reconfiguration or reset operation.
    State ownership/permissions and choosing its single installed path belong to
    deployment. This does not prevent a filesystem administrator making another
    database, and a request allowance is not a monetary spending limit.
    """
    def __init__(self,path,profile):
        self.path=Path(path).resolve();self.profile=profile
        # Re-parse even programmatically built dataclass instances.
        Profile.parse(_canonical(profile.public()))
        with self._connect() as db:self._profile(db)

    @classmethod
    def create(cls,path,profile):
        Profile.parse(_canonical(profile.public()))
        path=Path(path).resolve()
        # Existing evidence is never replaced, even if empty or malformed.
        try:
            with path.open('xb'):pass
        except FileExistsError:raise DeploymentError('ALLOWANCE_ALREADY_EXISTS') from None
        with closing(sqlite3.connect(path,timeout=2)) as db,db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE profile (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL, digest TEXT NOT NULL)')
            db.execute('CREATE TABLE claims (request_id TEXT PRIMARY KEY, body_digest TEXT NOT NULL, at_us INTEGER NOT NULL, result TEXT NOT NULL)')
            db.execute('INSERT INTO profile VALUES (1,?,?)',(_canonical(profile.public()),profile.digest))
        return cls(path,profile)

    def _connect(self):
        # mode=rw deliberately fails when missing; never silently reset allowance.
        return closing(sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=2))

    def _profile(self,db):
        rows=db.execute('SELECT body,digest FROM profile').fetchall()
        if rows!=[(_canonical(self.profile.public()),self.profile.digest)]:raise DeploymentError('PROFILE_MISMATCH')

    def claim(self,request_id,body_digest,deadline_us):
        if type(request_id) is not str or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',request_id):raise DeploymentError('INVALID_REQUEST_ID')
        if type(body_digest) is not str or not re.fullmatch(r'[a-f0-9]{64}',body_digest):raise DeploymentError('INVALID_BODY_DIGEST')
        if type(deadline_us) is not int:raise DeploymentError('INVALID_DEADLINE')
        try:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    self._profile(db)
                    now=time.time_ns()//1000
                    if not now<deadline_us<=now+30_000_000:raise DeploymentError('DEADLINE_EXPIRED_OR_INVALID')
                    if db.execute('SELECT 1 FROM claims WHERE request_id=?',(request_id,)).fetchone():raise DeploymentError('REQUEST_ALREADY_USED')
                    used=db.execute('SELECT COUNT(*) FROM claims').fetchone()[0]
                    if used>=self.profile.request_limit:raise DeploymentError('REQUEST_LIMIT_REACHED')
                    db.execute('INSERT INTO claims VALUES (?,?,?,?)',(request_id,body_digest,now,'IN_FLIGHT'))
                    db.commit()
                    return {'claimed':True,'used':used+1,'remaining':self.profile.request_limit-used-1,'profile_sha256':self.profile.digest}
                except Exception:
                    db.rollback();raise
        except sqlite3.Error:raise DeploymentError('ALLOWANCE_UNAVAILABLE') from None

    def finish(self,request_id,outcome):
        if outcome not in {'VERIFIED_STOP','FAILED','UNCERTAIN'}:raise DeploymentError('INVALID_OUTCOME')
        with self._connect() as db,db:
            self._profile(db)
            row=db.execute('SELECT result FROM claims WHERE request_id=?',(request_id,)).fetchone()
            if row is None:raise DeploymentError('REQUEST_NOT_CLAIMED')
            # First terminal result wins. A later observation never refunds quota.
            db.execute("UPDATE claims SET result=? WHERE request_id=? AND result='IN_FLIGHT'",(outcome,request_id))
            return db.execute('SELECT result FROM claims WHERE request_id=?',(request_id,)).fetchone()[0]

    def snapshot(self):
        with self._connect() as db:
            self._profile(db)
            counts=dict(db.execute('SELECT result,COUNT(*) FROM claims GROUP BY result'))
        used=sum(counts.values())
        return {'profile_sha256':self.profile.digest,'used':used,'remaining':self.profile.request_limit-used,'outcomes':counts}


def check_conversation_state(area, profile_path=None):
    """Inspect a prepared, dedicated C1 or C2 state before opening any SQLite file.

    Trusted filesystem ownership is still required; this does not protect
    against an administrator replacing files concurrently after inspection.
    """
    import stat
    area = Path(area)
    if not area.is_absolute() or ".." in area.parts or area.name != "conversation-provider":
        raise DeploymentError("INVALID_CONVERSATION_STATE_PATH")
    for parent in reversed((area, *area.parents)):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DeploymentError("LINK_OR_REPARSE_POINT")
        if not stat.S_ISDIR(info.st_mode):raise DeploymentError("WRONG_PATH_KIND")
    if {p.name for p in area.parent.iterdir()} != {"conversation-provider"}:
        raise DeploymentError("DEDICATED_CONVERSATION_RUNTIME_REQUIRED")
    allowed = {"profile.json", "allowance.sqlite", "allowance.sqlite-wal", "allowance.sqlite-shm"}
    names = {p.name for p in area.iterdir()}
    if not {"profile.json", "allowance.sqlite"} <= names:
        raise DeploymentError("CONVERSATION_STATE_NOT_PREPARED")
    if not names <= allowed:raise DeploymentError("UNEXPECTED_PROVIDER_STATE")
    for child in area.iterdir():
        info = child.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DeploymentError("LINK_OR_REPARSE_POINT")
        if not stat.S_ISREG(info.st_mode):raise DeploymentError("WRONG_PATH_KIND")
        if info.st_nlink != 1:raise DeploymentError("SHARED_STATE_FILE_REJECTED")
    if profile_path is not None:
        profile_path = Path(profile_path)
        if ".." in profile_path.parts or profile_path.absolute() != area / "profile.json":
            raise DeploymentError("CONVERSATION_PROFILE_LOCATION_MISMATCH")
    return area / "profile.json"
