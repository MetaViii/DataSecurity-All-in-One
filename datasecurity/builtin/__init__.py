from datasecurity.core.registry import Registry

from .csv_io import CsvReader, CsvWriter
from .filter_rows import FilterRows
from .json_output import JsonWriter
from .regex_check import RegexCheck
from .fields import PLUGINS as FIELD_PLUGINS
from .rows import PLUGINS as ROW_PLUGINS
from .validation import PLUGINS as VALIDATION_PLUGINS
from .tables import PLUGINS as TABLE_PLUGINS
from .codec import PLUGINS as CODEC_PLUGINS
from .datetime_fields import PLUGINS as DATE_PLUGINS
from .expression import CalculateColumn
from .file_inputs import PLUGINS as INPUT_PLUGINS
from .excel_output import ExcelWriter
from .advanced import PLUGINS as ADVANCED_PLUGINS
from .security import PLUGINS as SECURITY_PLUGINS
from .analysis import PLUGINS as ANALYSIS_PLUGINS
from .contest import PLUGINS as CONTEST_PLUGINS
from .correction import PLUGINS as CORRECTION_PLUGINS
from .extraction import PLUGINS as EXTRACTION_PLUGINS


def create_registry() -> Registry:
    registry = Registry()
    for plugin_type in (
        CsvReader,
        CsvWriter,
        FilterRows,
        JsonWriter,
        RegexCheck,
        *FIELD_PLUGINS,
        *ROW_PLUGINS,
        *VALIDATION_PLUGINS,
        *TABLE_PLUGINS,
        *CODEC_PLUGINS,
        *DATE_PLUGINS,
        *INPUT_PLUGINS,
        CalculateColumn,
        ExcelWriter,
        *ADVANCED_PLUGINS,
        *SECURITY_PLUGINS,
        *ANALYSIS_PLUGINS,
        *CONTEST_PLUGINS,
        *CORRECTION_PLUGINS,
        *EXTRACTION_PLUGINS,
    ):
        registry.register(plugin_type())
    return registry
