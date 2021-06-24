import logging
from datetime import datetime
from pathlib import Path


class TimedFileHandler(logging.FileHandler):
    """
    Custom FileHandler that deletes any logfiles in directory more than
    backupCount
    """

    def __init__(
        self, filename, backupCount, mode="a", date_pattern="%Y-%m-%d_%H-%M-%S"
    ):
        self.backup_count = backupCount
        self.filename = self.get_name(filename, date_pattern)
        self.delete()
        super().__init__(filename=self.filename, mode=mode)

    def get_name(self, log_name, date_pattern):
        t_now = datetime.now().strftime(date_pattern) + ".log"
        filename = log_name.strip(".log") + " " + t_now
        return filename

    def sorted_logfiles(self):
        """
        Sort log files recent first
        """
        folder = Path(self.filename).parent
        logfiles = []
        logfiles.extend(folder.glob("*.log"))
        logfiles.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        return logfiles

    def delete(self):
        """
        Deletes old log files when they exceed backup_count
        """
        all_logfiles = self.sorted_logfiles()
        if len(all_logfiles) >= self.backup_count:
            for file in all_logfiles[self.backup_count - 1 :]:
                file.unlink()
