def main(req):
    from backend_app import get_daily_summary as _impl

    return _impl(req)
