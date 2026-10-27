from urllib.parse import quote

from django.conf import settings
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticFilesStorage(StaticFilesStorage):
    """
    StaticFilesStorage whose URLs end with `?v=<settings.ASSET_VERSION>` (so `{% static "js/ours/init.js" %}` gives
    `/static/js/ours/init.js?v=2`).

    Browsers keep static files without being asked again, for a time they guess themselves (often days), so after a
    release visitors can keep running old JavaScript or CSS with the new pages. Changing ASSET_VERSION in `.env`
    (and recreating the django container) changes every address written into the pages, which are not cached, so
    every browser fetches the new files on its next page load. Files are stored under their normal names:
    `collectstatic` and the file server are unaffected.
    """

    def url(self, name):
        url = super().url(name)
        version = getattr(settings, 'ASSET_VERSION', '')
        if not name or not version:
            return url
        return f"{url}{'&' if '?' in url else '?'}v={quote(str(version), safe='')}"
