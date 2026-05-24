def main(req):
    from backend_app import get_alerts as _impl

    return _impl(req)
