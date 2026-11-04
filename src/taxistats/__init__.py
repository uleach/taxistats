"""taxistats — merge, de-duplicate and analyse Yandex Go ride-history exports."""

from .load import LoadReport, load_exports
from .schema import Ride, parse_record
from .stats import compute_all, to_frame

__all__ = ["LoadReport", "Ride", "compute_all", "load_exports", "parse_record", "to_frame"]
__version__ = "0.1.0"
