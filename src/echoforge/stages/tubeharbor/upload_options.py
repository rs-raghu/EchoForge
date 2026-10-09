"""Resolve editable upload fields once, preserving explicit empty/false values."""
from echoforge.core.storage import atomic_json, file_lock, read_json


ALIASES = {
    'visibility': ('privacy', 'privacyStatus'),
    'scheduleAt': ('schedule_at', 'schedule_time', 'scheduleTime', 'publishAt'),
    'categoryId': ('category_id',),
    'madeForKids': ('made_for_kids',),
    'thumbnailPath': ('thumbnail', 'thumbnail_path'),
}
FIELDS = {'title', 'description', 'tags', *ALIASES}


def normalize_layer(options):
    if not isinstance(options, dict):
        raise ValueError('Upload metadata must be an object')
    result = {key: value for key, value in options.items() if value is not None and key != 'metadata'}
    for canonical, aliases in ALIASES.items():
        for name in (canonical, *aliases):
            if name in result:
                result[canonical] = result[name]
                break
        for alias in aliases:
            result.pop(alias, None)
    return result


def normalize_upload_options(options):
    if not isinstance(options, dict):
        raise ValueError('Upload options must be an object')
    nested = options.get('metadata', {})
    if nested is None: nested = {}
    return {**normalize_layer(nested), **normalize_layer(options)}


def resolve_upload_options(project, options):
    stored = read_json(project / 'upload/youtube_metadata.json', {})
    return {**normalize_upload_options(stored), **normalize_upload_options(options)}


def persist_upload_options(project, options):
    """Store the accepted dialog snapshot so reopening cannot restore defaults."""
    provided = {key: value for key, value in normalize_upload_options(options).items() if key in FIELDS}
    if not provided: return
    path = project / 'upload/youtube_metadata.json'
    with file_lock(path.with_suffix('.lock')):
        stored = read_json(path, {})
        metadata = normalize_upload_options(stored)
        metadata = {key: value for key, value in metadata.items() if key in FIELDS}
        metadata.update(provided)
        atomic_json(path, {'metadata': metadata, 'approved': True})
