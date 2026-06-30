import logging
from sqlalchemy.orm import Session
from app.database.models import Template

logger = logging.getLogger(__name__)


def create_template(session: Session, name: str, text: str) -> Template:
    """Create a new message template."""
    name = name.strip()
    text = text.strip()

    template = Template(
        name=name,
        text=text,
        is_active=True,
    )
    session.add(template)
    session.commit()
    logger.info(f"Created template: {name}")
    return template


def list_templates(session: Session, include_inactive: bool = False) -> list[Template]:
    """Get all templates."""
    query = session.query(Template)
    if not include_inactive:
        query = query.filter(Template.is_active.is_(True))
    return query.all()


def get_template(session: Session, template_id: int) -> Template | None:
    """Get a specific template by ID."""
    return session.query(Template).filter(Template.id == template_id).first()


def get_template_by_name(session: Session, name: str) -> Template | None:
    """Check if template with name already exists."""
    return session.query(Template).filter(Template.name == name).first()


def template_name_exists(session: Session, name: str, exclude_id: int = None) -> bool:
    """Check if template name exists (excluding a specific ID if provided)."""
    query = session.query(Template).filter(Template.name == name.strip())
    if exclude_id:
        query = query.filter(Template.id != exclude_id)
    return query.first() is not None


def update_template_name(session: Session, template_id: int, new_name: str) -> bool:
    """Update template name. Returns True if successful."""
    template = get_template(session, template_id)
    if not template:
        logger.warning(f"Template {template_id} not found")
        return False

    new_name = new_name.strip()
    if template_name_exists(session, new_name, exclude_id=template_id):
        logger.warning(f"Template name '{new_name}' already exists")
        return False

    template.name = new_name
    session.commit()
    logger.info(f"Template {template_id} name updated to: {new_name}")
    return True


def update_template_text(session: Session, template_id: int, new_text: str) -> bool:
    """Update template text. Returns True if successful."""
    template = get_template(session, template_id)
    if not template:
        logger.warning(f"Template {template_id} not found")
        return False

    new_text = new_text.strip()
    template.text = new_text
    session.commit()
    logger.info(f"Template {template_id} text updated ({len(new_text)} chars)")
    return True


def disable_template(session: Session, template_id: int) -> bool:
    """Disable a template (soft delete)."""
    template = get_template(session, template_id)
    if not template:
        logger.warning(f"Template {template_id} not found")
        return False

    template.is_active = False
    session.commit()
    logger.info(f"Template {template_id} disabled")
    return True


def enable_template(session: Session, template_id: int) -> bool:
    """Re-enable a disabled template."""
    template = get_template(session, template_id)
    if not template:
        logger.warning(f"Template {template_id} not found")
        return False

    template.is_active = True
    session.commit()
    logger.info(f"Template {template_id} enabled")
    return True


def get_template_info(session: Session, template_id: int) -> dict | None:
    """Get detailed template information."""
    template = get_template(session, template_id)
    if not template:
        return None

    return {
        "id": template.id,
        "name": template.name,
        "text": template.text,
        "is_active": template.is_active,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def get_template_preview(text: str, max_length: int = 100) -> str:
    """Get a short preview of template text."""
    text = text.strip()
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text
