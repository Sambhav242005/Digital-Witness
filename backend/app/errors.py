class ApiFailure(Exception):
    def __init__(self, status, code, message, details=None):
        self.status = status
        self.error = {"code": code, "message": message, "details": details or {}}
        super().__init__(message)
