from rest_framework.exceptions import APIException


class ListRuleError(APIException):
    def __init__(self, status_code, code, detail):
        self.status_code = status_code
        super().__init__(detail=detail, code=code)
