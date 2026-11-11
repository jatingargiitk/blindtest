import re
import unicodedata


def slugify(text, sep="-", max_len=None):
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", sep, folded.lower()).strip(sep)
    if max_len is not None:
        slug = slug[:max_len]
    return slug
