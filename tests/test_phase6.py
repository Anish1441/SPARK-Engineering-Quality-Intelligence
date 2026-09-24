import pandas as pd
from core.analysis_engine import dataset_health,signal_control,record_assessment
def test_health():
    d=pd.DataFrame({"a":[1,2,3],"b":["x","y","z"]})
    assert dataset_health(d)["numeric_signals"]==1
def test_control():
    d=pd.DataFrame({"a":[1,2,3,100]})
    assert signal_control(d,"a")["eligible"]
def test_record():
    d=pd.DataFrame({"a":[1,2,3,100]})
    assert record_assessment(d,3)["score"]>0
