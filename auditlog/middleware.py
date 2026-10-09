import threading
import uuid

_thread_locals = threading.local()


def get_current_request():
    return getattr(_thread_locals, "request", None)


def get_current_user():
    req = get_current_request()
    user = getattr(req, "user", None) if req else None
    if user and getattr(user, "is_authenticated", False):
        return user
    return None


def get_request_id():
    req = get_current_request()
    return getattr(req, "audit_request_id", None) if req else None


class AuditContextMiddleware:
    """
    Stores request on thread-local storage so model signals can access:
      - user
      - request_id
      - ip
      - user_agent
      - session_key
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.audit_request_id = str(uuid.uuid4())
        _thread_locals.request = request
        try:
            return self.get_response(request)
        finally:
            _thread_locals.request = None
