from unittest import TestCase

import src.lib.app.superannotate as sa


class BaseTestCase(TestCase):
    PROJECT_NAME = ""
    PROJECT_DESCRIPTION = "Desc"
    PROJECT_TYPE = "Type"
    TEST_FOLDER_PTH = "data_set"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        BaseTestCase.PROJECT_NAME = BaseTestCase.__class__.__name__

    def setUp(self, *args, **kwargs):
        self.tearDown()
        self._project = sa.create_project(
            self.PROJECT_NAME, self.PROJECT_DESCRIPTION, self.PROJECT_TYPE
        )
        # todo check is it required

    def tearDown(self) -> None:
        projects = sa.search_projects(self.PROJECT_NAME, return_metadata=True)
        for project in projects:
            sa.delete_project(project)
