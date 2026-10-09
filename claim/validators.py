from pathlib import Path
from django.core.exceptions import ValidationError


def validate_pdf(upload):
    if not upload:
        return
    if Path(upload.name).suffix.lower() != '.pdf' or upload.size > 10 * 1024 * 1024:
        raise ValidationError('Upload a PDF of at most 10 MB.')
    position = upload.tell()
    upload.seek(0)
    signature = upload.read(5)
    upload.seek(position)
    if signature != b'%PDF-':
        raise ValidationError('The file is not a PDF.')
