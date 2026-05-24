def main(req):
    from backend_app import start_rfid_rebind_scan as _impl

    return _impl(req)
