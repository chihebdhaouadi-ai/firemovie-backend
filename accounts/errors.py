from rest_framework.exceptions import APIException


class ProfileError(APIException):
    status_code = 400

    def __init__(self, code, detail):
        super().__init__(detail=detail, code=code)
