def main(req):
    from backend_app import get_recent_feedings as _impl

    return _impl(req)
