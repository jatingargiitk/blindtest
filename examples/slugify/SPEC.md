# slugify

`slugify(text, sep="-", max_len=None) -> str`

1. The result is lowercase.
2. Accented Latin letters are folded to their plain ASCII letter: `"Café"` becomes `"cafe"`.
3. Every run of characters that is not an ASCII letter or digit becomes a single `sep`.
4. The result never starts or ends with `sep`.
5. If `max_len` is given, the result is at most `max_len` characters and still never ends with `sep`.
6. Text with no letters or digits gives `""`.
7. A `text` that is not a `str` raises `TypeError`.
