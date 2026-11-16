from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler


def _first_message(value):
    if isinstance(value, dict):
        for item in value.values():
            return _first_message(item)
        return ''
    if isinstance(value, list):
        return _first_message(value[0]) if value else ''
    return str(value)


def _code_for(exc):
    if isinstance(exc, APIException):
        codes = exc.get_codes()
        return codes if isinstance(codes, str) else 'error'
    if isinstance(exc, Http404):
        return 'not_found'
    if isinstance(exc, PermissionDenied):
        return 'permission_denied'
    return 'error'


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        detail = _first_message(exc.detail)
        code = 'validation_error'
    else:
        detail = str(response.data.get('detail', ''))
        code = _code_for(exc)

    response.data = {'detail': detail, 'code': code}
    return response
