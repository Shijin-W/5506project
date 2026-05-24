def main(req):
    from backend_app import resolve_alert as _impl

    return _impl(req)
