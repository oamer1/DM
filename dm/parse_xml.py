import os
from pathlib import Path
from lxml.etree import ElementTree as ET
from typing import Dict

try:
    import log

    LOGGER = log.getLogger(__name__)
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)

# LOGGER = log.getLogger(__name__)


class parse_xml:
    def __init__(self) -> None:
        self.config_dir_path = Path(os.environ["QC_CONFIG_DIR"])
        self.fname = self.get_project_name()

    def get_project_name(self) -> Path:
        fname = Path(os.environ["BATMAN_XML_SETTINGS_FILE"])
        if not fname.exists():
            LOGGER.error(f"{fname} NOT found")
            fname = self.config_dir_path / "project.xml"
        return fname

    def parse_project_section(self, section: str, key: str) -> str:
        """
        Parses given project.xml file and extracts the value of `key` attribute from
        top-level element `section` -> `<values>`.
        """
        et = ET()
        doc = et.parse(str(self.fname))

        try:
            section = doc.find(section)
            values = section.find("values")
            anon = values.find("anon")
            value = anon.attrib[key]
        except Exception as err:
            LOGGER.debug(f"Cannot parse {self.fname}: {err}")
            return ""

        return value

    def get_netlist_info(self) -> Dict:
        et = ET()
        doc = et.parse(str(self.fname))
        try:
            section = doc.find("Netlists")
            values = section.find("values")
            netlists = {}
            for netlist in values.getchildren():
                netlists[netlist.attrib["name"]] = {
                    key: netlist.attrib[key] for key in netlist.keys()
                }
            return netlists
        except Exception as err:
            LOGGER.debug(f"Cannot parse netlist info {self.fname}: {err}")
            return {}

    def get_email(self, user: str) -> str:
        """
        Get email_notify from config_dir / "project.xml" if exists
        else use f"{user}@qti.qualcomm.com"
        """
        try:

            LOGGER.info(f"Parsing {self.fname} to find email to notify...")
            email = self.parse_project_section(section="wtf", key="email_notify")

        except AttributeError:
            LOGGER.error("Project.xml is not updated")

        except Exception as e:
            LOGGER.error(f"Error: {e}", exc_info=True)

        else:
            LOGGER.info(f"project.xml is not updated, sending email to {user}")
            email = f"{user}@qti.qualcomm.com"
        LOGGER.info(f"Using email: {email}")

        return email
