from pathlib import Path
from lxml.etree import ElementTree as ET

try:
    import log

    LOGGER = log.getLogger(__name__)
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)

# LOGGER = log.getLogger(__name__)


def parse_project_xml(fname: Path, section="wtf", key="email_notify") -> str:
    """
    Parses given project.xml file and extracts the value of `key` attribute from
    top-level element `section` -> `<values>`.
    """
    if not fname.exists():
        LOGGER.error("%s NOT found", str(fname))
        return ""

    et = ET()
    doc = et.parse(str(fname))

    try:
        section = doc.find(section)
        values = section.find("values")
        anon = values.find("anon")
        value = anon.attrib[key]
        return value
    except Exception as err:
        LOGGER.exception("Cannot parse %s: %s", str(fname), str(err))
        return ""


def get_email(config_dir_path: Path, user: str) -> str:
    """
    Get email_notify from config_dir / "project.xml" if exists
    else use f"{user}@qti.qualcomm.com"
    """
    try:
        fname = config_dir_path / "project.xml"
        LOGGER.info(f"Parsing {str(fname)} to find email to notify...")
        email = parse_project_xml(fname)

    except AttributeError:
        LOGGER.error("Project.xml is not updated")

    except Exception as e:
        LOGGER.error(f"Error: {e}", exc_info=True)

    else:
        LOGGER.info(f"project.xml is not updated, sending email to {user}")
        email = f"{user}@qti.qualcomm.com"
    LOGGER.info(f"Using email: {email}")

    return email
