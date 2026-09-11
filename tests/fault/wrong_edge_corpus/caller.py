"""Five wrong-edge counter-cases (get/update family)."""
import api
from session import Session
from store import Store

def case1_dict_get(cfg):
    # dict.get must never link to api.get
    return cfg.get("k")

def case2_session_get():
    s = Session()
    # typed receiver -> Session.get, not api.get
    return s.get("http://x")

def case3_unknown_receiver(obj):
    # unknowable receiver type -> pending, NOT api.get
    return obj.get("k")

def case4_store_update():
    st = Store()
    return st.update({"a": 1})

def case5_shadowed_local():
    def get(x):
        return x + 1
    return get(5)
