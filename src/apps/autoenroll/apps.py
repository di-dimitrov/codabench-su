from django.apps import AppConfig


class AutoenrollConfig(AppConfig):
    # If your INSTALLED_APPS entries are written as "apps.<name>", change this
    # to "apps.autoenroll" and place the folder under src/apps/ accordingly.
    name = "autoenroll"
    verbose_name = "SemEval 2027 Task 9 — cross-competition auto-enrollment"

    def ready(self):
        # Importing here registers the post_save receiver in every process
        # (web + worker) that loads Django apps.
        from . import signals  # noqa: F401
