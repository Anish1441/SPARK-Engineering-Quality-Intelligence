from __future__ import annotations
import json,re,uuid
from pathlib import Path
import pandas as pd
class DatasetError(Exception): pass
SAFE=re.compile(r"[^A-Za-z0-9_.-]+")
class DatasetManager:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.registry=self.root/"registry.json"
        if not self.registry.exists(): self.registry.write_text("[]",encoding="utf-8")
    def _read(self): return json.loads(self.registry.read_text(encoding="utf-8"))
    def _write(self,x):
        t=self.registry.with_suffix(".tmp"); t.write_text(json.dumps(x,indent=2),encoding="utf-8"); t.replace(self.registry)
    def _load(self,p):
        try:
            if p.suffix.lower()==".csv": return pd.read_csv(p,low_memory=False)
            if p.suffix.lower() in {".xlsx",".xls"}: return pd.read_excel(p)
        except Exception as e: raise DatasetError(f"Dataset could not be read: {e}") from e
        raise DatasetError("Only CSV and Excel datasets are supported.")
    def save_upload(self,file):
        name=SAFE.sub("_",Path(file.filename).name).strip("._")
        if not name or Path(name).suffix.lower() not in {".csv",".xlsx",".xls"}: raise DatasetError("Only CSV and Excel datasets are supported.")
        did=uuid.uuid4().hex; target=self.root/(did+Path(name).suffix.lower()); file.save(target)
        try: df=self._load(target)
        except DatasetError: target.unlink(missing_ok=True); raise
        if df.empty: target.unlink(missing_ok=True); raise DatasetError("The dataset contains no records.")
        item={"dataset_id":did,"filename":name,"rows":int(len(df)),"columns":int(len(df.columns)),"numeric_columns":int(len(df.select_dtypes(include="number").columns)),"missing_cells":int(df.isna().sum().sum()),"size_bytes":int(target.stat().st_size)}
        self._write([item]+self._read()); return item
    def list(self): return self._read()
    def get(self,did):
        for item in self._read():
            if item["dataset_id"]==did:
                p=next(iter(self.root.glob(did+".*")),None)
                if p is None: raise DatasetError("Dataset file is missing.")
                return item,self._load(p)
        raise DatasetError("Dataset not found.")
    def activate(self,did):
        item,_=self.get(did); rows=self._read()
        for x in rows: x["active"]=x["dataset_id"]==did
        self._write(rows); item["active"]=True; return item
    def remove(self,did):
        self.get(did)
        for p in self.root.glob(did+".*"): p.unlink(missing_ok=True)
        self._write([x for x in self._read() if x["dataset_id"]!=did]); return {"removed":did}
