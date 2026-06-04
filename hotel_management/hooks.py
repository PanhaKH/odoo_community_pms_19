import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Keep partner profile columns available during registry upgrade reads."""
    env.cr.execute("""
        ALTER TABLE res_partner
        ADD COLUMN IF NOT EXISTS hotel_date_of_birth date
    """)
    env.cr.execute("""
        ALTER TABLE res_partner
        ADD COLUMN IF NOT EXISTS hotel_gender varchar
    """)


def post_init_hook(env):
    """Create hotel accounting defaults after the registry is ready."""
    try:
        env['hotel.config.setup'].sudo().setup_default_hotel_accounting()
    except Exception:
        _logger.exception("Hotel default accounting setup failed during post-init hook.")
        raise
