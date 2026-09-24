from __future__ import annotations
import json,uuid
from pathlib import Path
from datetime import datetime,timezone
ACTIONS={"ACCEPT","WATCH","RETEST","HOLD","REJECT","QUARANTINE","ABSTAIN"}; RESPONSES={"AGREE","OVERRIDE","NOTE"}
class QAManager:
    def __init__(self,root): self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def _p(self,d): return self.root/f"{d}.json"
    def list(self,d):
        p=self._p(d)
        if not p.exists(): return []
        try:return json.loads(p.read_text(encoding="utf-8"))
        except Exception:return []
    def save(self,d,payload):
        action=str(payload.get("action","")).upper().strip(); response=str(payload.get("response","")).upper().strip()
        if action not in ACTIONS: raise ValueError("Invalid QA action.")
        if response and response not in RESPONSES: raise ValueError("Invalid QA response.")
        if response=="OVERRIDE" and str(payload.get("override_action","")).upper() not in ACTIONS: raise ValueError("An override action is required.")
        item=dict(payload); item.update(id=uuid.uuid4().hex,dataset_id=d,timestamp=datetime.now(timezone.utc).isoformat())
        rows=self.list(d)+[item]; t=self._p(d).with_suffix(".tmp"); t.write_text(json.dumps(rows,indent=2),encoding="utf-8"); t.replace(self._p(d)); return item
