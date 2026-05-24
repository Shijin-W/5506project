def main(req):
    from backend_app import get_alert_history as _impl

    return _impl(req)
