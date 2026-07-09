import logging
import traceback


class SingleLineFormatter(logging.Formatter):
    def __init__(
        self,
        fmt=None,
        datefmt=None,
        style="%",
        validate=True,
        *,
        defaults=None,
    ):
        super().__init__(
            fmt=fmt,
            datefmt=datefmt,
            style=style,
            validate=validate,
            defaults=defaults,
        )

    def formatException(self, ei):
        text = "".join(traceback.format_exception(*ei))
        return text.replace("\n", "\\n")

    def format(self, record):
        record.message = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        else:
            record.exc_text = None

        message = self.formatMessage(record)
        if record.exc_text:
            message = f"{message} | exc={record.exc_text}"
        return message
