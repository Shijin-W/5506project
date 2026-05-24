def main(req):
    from backend_app import get_frontend_data as _impl

    return _impl(req)
