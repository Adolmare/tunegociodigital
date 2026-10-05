from contextvars import ContextVar
_tenant = ContextVar("tenant", default=None)
def set_tenant(t): _tenant.set(t)
def get_tenant(): return _tenant.get()
def clear_tenant(): _tenant.set(None)