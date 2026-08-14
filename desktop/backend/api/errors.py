from fastapi import HTTPException


def translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError): return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError): return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError): return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))
