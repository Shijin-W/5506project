def main(req):
    from backend_app import get_current_status as _impl

    return _impl(req)
