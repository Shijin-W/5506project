def main(req):
    from backend_app import update_cat_rfid as _impl

    return _impl(req)
