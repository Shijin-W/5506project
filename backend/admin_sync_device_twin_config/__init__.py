def main(req):
    from backend_app import sync_device_twin_config as _impl

    return _impl(req)
