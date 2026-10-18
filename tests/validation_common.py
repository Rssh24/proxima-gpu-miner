"""Small shared helpers for source-bound local build validation."""
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def child_path(root, relative):
    root=Path(root).resolve()
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise RuntimeError('Manifest contains an invalid relative path')
    target=(root/relative).resolve()
    if target==root or not target.is_relative_to(root):
        raise RuntimeError('Manifest path escapes its declared root')
    return target


def verify_hash_map(root, hashes):
    if not isinstance(hashes,dict) or not hashes:
        raise RuntimeError('Required build hash map is empty')
    for relative,expected in hashes.items():
        if not isinstance(expected,str) or len(expected)!=64:
            raise RuntimeError('Invalid digest for '+str(relative))
        path=child_path(root,relative)
        if not path.is_file() or sha256(path)!=expected.lower():
            raise RuntimeError('Build/source hash mismatch: '+relative)


def upstream_hashes(root):
    root=Path(root).resolve()
    return {p.relative_to(root).as_posix():sha256(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '.git' not in p.parts and
            (p.suffix=='.go' or p.name in ('go.mod','go.sum'))}


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)
