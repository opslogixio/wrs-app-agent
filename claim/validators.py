"""Validate claim attachments without trusting filenames or client MIME types."""
from io import BytesIO
from pathlib import Path
import warnings

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ATTACHMENT_CONTENT_TYPES = {
    '.pdf': 'application/pdf', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
}
IMAGE_FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.gif': 'GIF'}


def validate_claim_file(upload):
    if not upload:
        return
    extension = Path(upload.name).suffix.lower()
    if extension not in ATTACHMENT_CONTENT_TYPES or upload.size > MAX_UPLOAD_SIZE:
        raise ValidationError('Upload a PDF, PNG, JPEG/JPG, or GIF of at most 10 MB.')
    position = upload.tell()
    try:
        upload.seek(0)
        if extension == '.pdf':
            if upload.read(5) != b'%PDF-':
                raise ValidationError('The file is not a PDF.')
            return
        content = upload.read(MAX_UPLOAD_SIZE + 1)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != IMAGE_FORMATS[extension]:
                    raise ValidationError('The image format does not match its filename extension.')
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValidationError('Images must contain at most 20 million pixels.')
                image.verify()
            # Decode pixels too: some formats verify headers without reading image data.
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError('Upload a valid PNG, JPEG/JPG, or GIF image.') from error
    finally:
        upload.seek(position)
