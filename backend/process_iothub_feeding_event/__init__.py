def main(events):
    from backend_app import process_iothub_feeding_event as _impl

    return _impl(events)
