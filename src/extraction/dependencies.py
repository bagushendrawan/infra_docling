from fastapi import Request


def get_worker(request: Request):
    return request.app.state.worker
