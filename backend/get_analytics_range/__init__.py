def main(req):
    from backend_app import get_analytics_range as _impl

    return _impl(req)
