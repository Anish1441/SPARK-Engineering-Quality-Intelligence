from pathlib import Path
class PipelineAdapter:
    def __init__(self,root): self.root=Path(root)
    def status(self): return {"configured_root":str(self.root),"accessible":self.root.exists(),"mode":"READ-ONLY","prediction_available":False,"message":"No model output is fabricated."}
    def assess(self,df,index): return {"available":False,"mode":"PIPELINE NOT CONNECTED","prediction":None,"confidence":None,"message":"Connect the validated inference contract to expose genuine model output."}
