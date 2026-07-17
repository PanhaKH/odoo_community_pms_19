def post_init_hook(env):
    env["hotel.room.service.outlet"].sudo()._ensure_default_room_service_setup()
    env["hotel.room.service.room.token"].sudo().action_generate_missing_room_tokens()


def uninstall_hook(env):
    """Hide module-provisioned POS configs when Room Service is removed."""
    outlet_model = env["hotel.room.service.outlet"].sudo()
    pos_config_model = env["pos.config"].sudo()

    outlets = outlet_model.search(["|", ("code", "=", "ROOM"), ("name", "=", "Room Service")])
    configs = outlets.mapped("pos_config_id")
    configs |= pos_config_model.search([
        ("name", "in", ["Room Service", "Room Service POS"]),
        ("self_ordering_mode", "in", ["mobile", "consultation"]),
    ])
    configs = configs.filtered(lambda config: config.exists())

    for config in configs:
        draft_orders = config.session_ids.order_ids.filtered(lambda order: order.state == "draft")
        if draft_orders:
            draft_orders.write({"state": "cancel"})

        open_sessions = config.session_ids.filtered(lambda session: session.state in ["opening_control", "opened"])
        empty_open_sessions = open_sessions.filtered(lambda session: not session.order_ids.filtered(lambda order: order.state not in ["draft", "cancel"]))
        if empty_open_sessions:
            empty_open_sessions.write({"state": "closed"})

        env.cr.execute(
            """
            UPDATE pos_config
               SET active = false,
                   self_ordering_mode = 'nothing',
                   self_ordering_service_mode = 'counter'
             WHERE id = %s
            """,
            [config.id],
        )
