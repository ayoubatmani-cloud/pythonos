class CancelledError(BaseException):
    pass

class TimeoutError(Exception):
    pass

class InvalidStateError(Exception):
    pass

class SendfileNotAvailableError(RuntimeError):
    pass
