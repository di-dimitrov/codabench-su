import pytest


@pytest.fixture(autouse=True)
def _no_task9_group(settings):
    """
    The Task 9 auto-enrollment (apps/autoenroll) is keyed on production competition PKs. Switch it off for the
    rest of the suite so factory-made competitions that happen to get those PKs don't share participant status.
    Tests of the feature itself set their own group with override_settings.
    """
    settings.TASK9_COMPETITION_IDS = []
    settings.TASK9_TITLE_PREFIX = "__no_task9_competitions_in_tests__"
