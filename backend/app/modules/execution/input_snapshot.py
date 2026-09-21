"""The existing ordinary Run input digest protocol, shared by creation and use."""
import hashlib
import json


def input_snapshot_hash(parameters_json: str, files: dict, skill_hash: str) -> str:
    # Preserve the established byte-level parameter serialization and canonical
    # binding serialization. Changing this would invalidate existing Run hashes.
    if not isinstance(json.loads(parameters_json), dict) or not isinstance(files, dict):
        raise ValueError("Task input snapshot must contain objects")
    parts = []
    for role, binding in files.items():
        items = binding if isinstance(binding, list) else ([binding] if binding else [])
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
                raise ValueError("Task file digest is missing")
            parts.append(f"{role}:{item['sha256']}")
    file_hash = hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()
    canonical_files = json.dumps(files, ensure_ascii=False, sort_keys=True)
    payload_hash = hashlib.sha256((parameters_json + canonical_files + skill_hash).encode()).hexdigest()
    return hashlib.sha256(f"{file_hash}:{payload_hash}".encode()).hexdigest()
