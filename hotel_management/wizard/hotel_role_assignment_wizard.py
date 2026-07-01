from odoo import api, fields, models, _


class HotelRoleAssignmentWizard(models.TransientModel):
    _name = 'hotel.role.assignment.wizard'
    _description = 'Assign Hotel Roles'

    user_id = fields.Many2one('res.users', string="User", required=True, readonly=True)

    role_front_office = fields.Boolean(string="Front Office")
    role_night_auditor = fields.Boolean(string="Night Auditor")
    role_front_office_manager = fields.Boolean(string="Front Office Manager")
    role_account_receivable = fields.Boolean(string="Account Receivable")
    role_housekeeper = fields.Boolean(string="Housekeeper")
    role_housekeeping_user = fields.Boolean(string="Housekeeping User")
    role_housekeeping_supervisor = fields.Boolean(string="Housekeeping Supervisor")
    role_housekeeping_manager = fields.Boolean(string="Housekeeping Manager")
    role_hotel_manager = fields.Boolean(string="Hotel Manager")

    effective_role_summary = fields.Text(
        string="Effective Roles After Inheritance",
        compute='_compute_role_messages',
        readonly=True,
    )
    role_explanation = fields.Text(
        string="Inheritance Notes",
        compute='_compute_role_messages',
        readonly=True,
    )
    warning_message = fields.Text(
        string="Role Warning",
        compute='_compute_role_messages',
        readonly=True,
    )

    _ROLE_FIELD_BY_KEY = {
        'front_office': 'role_front_office',
        'night_auditor': 'role_night_auditor',
        'front_office_manager': 'role_front_office_manager',
        'account_receivable': 'role_account_receivable',
        'housekeeper': 'role_housekeeper',
        'housekeeping_user': 'role_housekeeping_user',
        'housekeeping_supervisor': 'role_housekeeping_supervisor',
        'housekeeping_manager': 'role_housekeeping_manager',
        'hotel_manager': 'role_hotel_manager',
    }

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        user = self.env['res.users'].browse(values.get('user_id') or self.env.context.get('active_id')).exists()
        if not user:
            return values

        values['user_id'] = user.id
        role_groups = user._hotel_role_groups_by_key()
        target_groups = self.env['res.groups'].browse([spec['group'].id for spec in role_groups.values()])
        selected_groups = user.group_ids & target_groups
        implied_by_selected = selected_groups.mapped('all_implied_ids') - selected_groups
        explicit_groups = selected_groups - implied_by_selected

        for key, field_name in self._ROLE_FIELD_BY_KEY.items():
            group = role_groups.get(key, {}).get('group')
            if group and field_name in fields_list:
                values[field_name] = group in explicit_groups
        return values

    def _selected_role_groups(self):
        self.ensure_one()
        role_groups = self.user_id._hotel_role_groups_by_key()
        selected = self.env['res.groups']
        for key, field_name in self._ROLE_FIELD_BY_KEY.items():
            group = role_groups.get(key, {}).get('group')
            if group and self[field_name]:
                selected |= group
        return selected

    @api.depends(
        'role_front_office',
        'role_night_auditor',
        'role_front_office_manager',
        'role_account_receivable',
        'role_housekeeper',
        'role_housekeeping_user',
        'role_housekeeping_supervisor',
        'role_housekeeping_manager',
        'role_hotel_manager',
    )
    def _compute_role_messages(self):
        for wizard in self:
            selected_groups = wizard._selected_role_groups() if wizard.user_id else self.env['res.groups']
            effective_groups = selected_groups | selected_groups.mapped('all_implied_ids')
            labels = wizard.user_id._hotel_role_labels_from_groups(effective_groups) if wizard.user_id else []
            wizard.effective_role_summary = "\n".join(labels) if labels else _("No hotel operational roles selected.")

            notes = []
            if wizard.role_night_auditor:
                notes.append(_("Night Auditor includes Front Office."))
            if wizard.role_front_office_manager:
                notes.append(_("Front Office Manager includes Night Auditor and Front Office."))
            if wizard.role_housekeeping_user:
                notes.append(_("Housekeeping User includes Housekeeper."))
            if wizard.role_housekeeping_supervisor:
                notes.append(_("Housekeeping Supervisor includes Housekeeping User and Housekeeper."))
            if wizard.role_housekeeping_manager:
                notes.append(_("Housekeeping Manager includes Housekeeping Supervisor, Housekeeping User, and Housekeeper."))
            if wizard.role_hotel_manager:
                notes.append(_("Hotel Manager includes Front Office Manager, Night Auditor, Front Office, Housekeeper, and Account Receivable."))
            wizard.role_explanation = "\n".join(notes)

            warnings = []
            front_selected = wizard.role_front_office or wizard.role_night_auditor or wizard.role_front_office_manager
            housekeeping_selected = (
                wizard.role_housekeeper
                or wizard.role_housekeeping_user
                or wizard.role_housekeeping_supervisor
                or wizard.role_housekeeping_manager
            )
            if front_selected and housekeeping_selected:
                warnings.append(_("Risky mix: Front Office/Night Auditor roles combined with Housekeeping roles."))
            if housekeeping_selected and wizard.role_account_receivable:
                warnings.append(_("Risky mix: Housekeeping roles combined with Account Receivable."))
            wizard.warning_message = "\n".join(warnings)

    def action_apply_roles(self):
        self.ensure_one()
        self.env['res.users']._check_hotel_role_assignment_access()

        role_groups = self.user_id._hotel_role_groups_by_key()
        target_groups = self.env['res.groups'].browse([spec['group'].id for spec in role_groups.values()])
        selected_groups = self._selected_role_groups()

        commands = [(3, group.id, 0) for group in target_groups]
        commands += [(4, group.id, 0) for group in selected_groups]
        self.user_id.sudo().write({'group_ids': commands})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hotel Roles Updated'),
                'message': _('Hotel role groups were updated for %s.') % self.user_id.display_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
