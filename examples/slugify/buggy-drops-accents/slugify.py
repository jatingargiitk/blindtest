import re


def slugify(text, sep="-", max_len=None):
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    slug = re.sub(r"[^a-z0-9]+", sep, text.lower()).strip(sep)
    if max_len is not None:
        slug = slug[:max_len].rstrip(sep)
    return slug
