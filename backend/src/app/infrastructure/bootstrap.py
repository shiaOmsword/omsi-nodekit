from app.ports import JobRepository
from framework.database import SQLiteDatabase
from framework.utils import PrivateFiles

from .schema import MIGRATIONS


class StorageBootstrap:
    def __init__(self, database: SQLiteDatabase, files: PrivateFiles, jobs: JobRepository):
        self.database = database
        self.files = files
        self.jobs = jobs

    def initialize(self):
        self.database.initialize(MIGRATIONS)
        self.files.initialize()
        self.jobs.recover()
