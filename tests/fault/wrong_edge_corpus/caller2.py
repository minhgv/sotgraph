"""More receiver-collision counter-cases."""
import api
from session import Session

class Repo:
    def fetch(self, key):
        return key

class Service(Repo):
    def run(self, key):
        # self has NO 'get' in this class; MRO base lacks it too.
        # must NOT link to api.get -> pending.
        return self.get(key)

class Holder:
    def __init__(self):
        self.s = Session()
    def go(self, url):
        # attribute receiver self.s -> Session.get via field type
        return self.s.get(url)

def qualified_api_get(k):
    # REAL call to api.get — the decoy edge that SHOULD exist
    return api.get(k)
