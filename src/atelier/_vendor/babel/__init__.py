"""Minimal babel stub — implements only what courlan.filters needs.

courlan uses babel solely for BCP47 language-tag prefix extraction:
    Locale.parse(segment, sep=delimiter).language == language

The full babel package ships ~32 MB of locale data files that are never
read at runtime.  This stub replaces it in production bundles.
"""


class UnknownLocaleError(ValueError):
    """Raised by Locale.parse for identifiers that are not valid locale tags."""


class Locale:
    """Minimal locale object — exposes only the .language attribute."""

    def __init__(self, language: str) -> None:
        self.language = language

    @classmethod
    def parse(cls, identifier: str, sep: str = "_") -> "Locale":
        """Parse a BCP47-style locale tag and return a Locale.

        Raises UnknownLocaleError when the language subtag is not a 2-or-3
        letter alpha string (mirrors what babel validates for the common case).
        """
        delimiter = sep if sep in identifier else "-"
        lang = identifier.split(delimiter)[0].lower()
        if not (2 <= len(lang) <= 3 and lang.isalpha()):
            raise UnknownLocaleError(f"unknown locale identifier: {identifier!r}")
        return cls(lang)
