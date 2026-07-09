import logging


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level=logging.INFO):
        if isinstance(max_level, str):
            max_level = int(logging.getLevelName(max_level))
        self.max_level = max_level
        super().__init__()

    def filter(self, record):
        return record.levelno <= self.max_level
