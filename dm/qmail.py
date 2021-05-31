import getpass
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List

import jinja2


def send_email(
    subject: str,
    sender: str,
    recipients: List[str],
    content: Dict,
    command_template: str,
    attachment: "Path" = None,
    smtp_host: str = "localhost",
) -> int:
    """
    Sends an email with `subject`, from `sender` to `recipients` with the given
    `content` body using Email.html template.
    """
    # Map command to its respective html template
    Email_templates = {
        "integrate": "EMAIL_Integrate.html",
        "mkbranch": "EMAIL_Mkbranch.html",
        "release": "EMAIL_Release.html",
        "snapshot_submit": "EMAIL_Snapshot.html",
        "submit": "EMAIL_Submit.html",
        "request_branch": "JIRA_RequestBranch.html",
        "JIRA_ticket": "JIRA_ticket.html",
    }
    user = getpass.getuser()
    if command_template == "request_branch":
        subject = f"New Branch Requested by {user}"
    else:
        subject = f"Wtf {command_template} command"

    commands = list(Email_templates.keys())

    if command_template not in commands:
        raise ValueError(f"Unknown Command : {command_template} not in {commands}")

    Email_file = Email_templates[command_template]
    # Load EMAIL_Submit.html template
    # File_path = str(Path(os.environ["RFA_MODELERS_DIR"]) / "dm")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(
            searchpath="/prj/analog/blaster_eval/sandiego/chips/reference/reference_v100/work/mgajjar/REFERENCE/verif_modules/rfa_modelers/python3/dm/Email_template/"
        )
    )
    # env = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath = File_path))
    mail_template = env.get_template(Email_file)
    # Place contents in content template placeholder
    html_body = mail_template.render(content=content)

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    # Attach log file if a path is passed
    if attachment:
        file_path = attachment
        file_name = file_path.name

        with open(file_path, "rb") as f:
            log_file_attachement = MIMEApplication(f.read())
            log_file_attachement.add_header(
                "Content-Disposition", "attachment", filename=file_name
            )
            msg.attach(log_file_attachement)

    s = smtplib.SMTP(smtp_host)
    s.send_message(msg)
    s.quit()
    # try:
    #    with smtplib.SMTP(smtp_host) as server:
    #        server.starttls()
    #        server.send_message(msg)
    # except Exception:
    #   LOGGER.exception("Could not send Email.")
    #   return 1
    return 0
