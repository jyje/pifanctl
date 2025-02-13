from enum import Enum

class LogLevels(str, Enum):
    """
    Log levels
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    def __str__(self):
        return self.value
    
    @classmethod
    def list(cls):
        return [member.value for member in cls]
