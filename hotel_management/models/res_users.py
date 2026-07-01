from html import escape

from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    hotel_staff_signature = fields.Binary(
        string="Staff E-Signature",
        attachment=True,
    )
    hotel_staff_signature_updated_at = fields.Datetime(
        string="Staff E-Signature Updated At",
        readonly=True,
    )
    hotel_effective_role_summary = fields.Text(
        string="Effective Hotel Roles",
        compute='_compute_hotel_effective_role_summary',
        compute_sudo=True,
    )
    hotel_feature_lost_found_read = fields.Boolean(
        string="Lost & Found Read",
        compute='_compute_hotel_feature_lost_found_access',
        inverse='_inverse_hotel_feature_lost_found_access',
        compute_sudo=True,
    )
    hotel_feature_lost_found_create = fields.Boolean(
        string="Lost & Found Create",
        compute='_compute_hotel_feature_lost_found_access',
        inverse='_inverse_hotel_feature_lost_found_access',
        compute_sudo=True,
    )
    hotel_feature_lost_found_write = fields.Boolean(
        string="Lost & Found Edit",
        compute='_compute_hotel_feature_lost_found_access',
        inverse='_inverse_hotel_feature_lost_found_access',
        compute_sudo=True,
    )
    hotel_feature_lost_found_delete = fields.Boolean(
        string="Lost & Found Delete",
        compute='_compute_hotel_feature_lost_found_access',
        inverse='_inverse_hotel_feature_lost_found_access',
        compute_sudo=True,
    )
    hotel_feature_guest_request_read = fields.Boolean(
        string="Guest Requests Read",
        compute='_compute_hotel_feature_guest_request_access',
        inverse='_inverse_hotel_feature_guest_request_access',
        compute_sudo=True,
    )
    hotel_feature_guest_request_create = fields.Boolean(
        string="Guest Requests Submit",
        compute='_compute_hotel_feature_guest_request_access',
        inverse='_inverse_hotel_feature_guest_request_access',
        compute_sudo=True,
    )
    hotel_feature_guest_request_write = fields.Boolean(
        string="Guest Requests Edit",
        compute='_compute_hotel_feature_guest_request_access',
        inverse='_inverse_hotel_feature_guest_request_access',
        compute_sudo=True,
    )
    hotel_feature_guest_request_delete = fields.Boolean(
        string="Guest Requests Delete",
        compute='_compute_hotel_feature_guest_request_access',
        inverse='_inverse_hotel_feature_guest_request_access',
        compute_sudo=True,
    )
    hotel_feature_access_matrix_html = fields.Html(
        string="Hotel Feature Access Matrix",
        compute='_compute_hotel_feature_access_matrix_html',
        compute_sudo=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if 'hotel_staff_signature' in vals:
                vals['hotel_staff_signature_updated_at'] = now
        return super().create(vals_list)

    def write(self, vals):
        if 'hotel_staff_signature' in vals:
            vals = dict(vals, hotel_staff_signature_updated_at=fields.Datetime.now())
        return super().write(vals)

    @api.model
    def _hotel_role_group_specs(self):
        return [
            ('front_office', _('Front Office'), 'hotel_management.group_hotel_front_office'),
            ('night_auditor', _('Night Auditor'), 'hotel_management.group_hotel_night_auditor'),
            ('front_office_manager', _('Front Office Manager'), 'hotel_management.group_hotel_front_office_manager'),
            ('account_receivable', _('Account Receivable'), 'hotel_management.group_hotel_account_receivable'),
            ('housekeeper', _('Housekeeper'), 'hotel_management.group_hotel_housekeeper'),
            ('housekeeping_user', _('Housekeeping User'), 'hotel_housekeeping_app.group_housekeeping_user'),
            ('housekeeping_supervisor', _('Housekeeping Supervisor'), 'hotel_housekeeping_app.group_housekeeping_supervisor'),
            ('housekeeping_manager', _('Housekeeping Manager'), 'hotel_housekeeping_app.group_housekeeping_manager'),
            ('hotel_manager', _('Hotel Manager'), 'hotel_management.group_hotel_manager'),
        ]

    @api.model
    def _hotel_role_groups_by_key(self):
        groups = {}
        for key, label, xmlid in self._hotel_role_group_specs():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups[key] = {'label': label, 'xmlid': xmlid, 'group': group}
        return groups

    @api.model
    def _check_hotel_role_assignment_access(self):
        if (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('hotel_management.group_hotel_system_admin')
        ):
            return
        raise AccessError(_("Only System users or Hotel System Admin can assign hotel roles."))

    @api.model
    def _hotel_lost_found_feature_groups(self):
        groups = {}
        for key, xmlid in {
            'read': 'hotel_management.hotel_feature_lost_found_read',
            'create': 'hotel_management.hotel_feature_lost_found_create',
            'write': 'hotel_management.hotel_feature_lost_found_write',
            'delete': 'hotel_management.hotel_feature_lost_found_delete',
        }.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups[key] = group
        return groups

    @api.model
    def _hotel_guest_request_feature_groups(self):
        groups = {}
        for key, xmlid in {
            'read': 'hotel_management.hotel_feature_guest_request_read',
            'create': 'hotel_management.hotel_feature_guest_request_submit',
            'write': 'hotel_management.hotel_feature_guest_request_write',
            'delete': 'hotel_management.hotel_feature_guest_request_delete',
        }.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups[key] = group
        return groups

    @api.model
    def _hotel_guest_request_legacy_raw_groups(self):
        groups = self.env['res.groups']
        for xmlid in (
            'hotel_management.hotel_feature_guest_request_create',
            'hotel_management.hotel_feature_guest_request_write',
            'hotel_management.hotel_feature_guest_request_delete',
        ):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    @api.model
    def _hotel_feature_role_specs(self):
        return {
            'front_office': (_('Front Office'), 'hotel_management.group_hotel_front_office'),
            'night_auditor': (_('Night Auditor'), 'hotel_management.group_hotel_night_auditor'),
            'front_office_manager': (_('Front Office Manager'), 'hotel_management.group_hotel_front_office_manager'),
            'account_receivable': (_('Account Receivable'), 'hotel_management.group_hotel_account_receivable'),
            'housekeeper': (_('Housekeeper'), 'hotel_management.group_hotel_housekeeper'),
            'housekeeping_user': (_('Housekeeping User'), 'hotel_housekeeping_app.group_housekeeping_user'),
            'housekeeping_supervisor': (_('Housekeeping Supervisor'), 'hotel_housekeeping_app.group_housekeeping_supervisor'),
            'housekeeping_manager': (_('Housekeeping Manager'), 'hotel_housekeeping_app.group_housekeeping_manager'),
            'hotel_manager': (_('Hotel Manager'), 'hotel_management.group_hotel_manager'),
            'hotel_system_admin': (_('Hotel System Admin'), 'hotel_management.group_hotel_system_admin'),
            'odoo_system': (_('Odoo System'), 'base.group_system'),
            'accounting_manager': (_('Accounting Manager'), 'account.group_account_manager'),
        }

    @api.model
    def _hotel_feature_matrix_specs(self):
        planned = _('Planned / Not editable yet')
        return [
            (_('Dashboard'), [
                (_('Hotel Dashboard'), {'front_office', 'housekeeper'}, _('Dashboard / Open'), planned),
                (_('Room Status Live'), {'front_office'}, _('Dashboard / Open'), planned),
                (_('Occupancy Chart'), {'night_auditor'}, _('Report / Open'), planned),
                (_('Occupancy Comparison'), {'front_office'}, _('Dashboard / Open'), planned),
                (_('Revenue Forecast'), {'night_auditor'}, _('Report / Open'), planned),
                (_('Pivot Analytics'), {'night_auditor'}, _('Report / Open'), planned),
            ]),
            (_('Front Desk'), [
                (_('Floor Plan Map'), {'front_office'}, _('Client Action / Open'), planned),
                (_('Room Chart'), {'front_office'}, _('Client Action / Open'), _('Planned / Not editable yet. Drag/drop remains controlled by existing security.')),
                (_('Availability Grid'), {'front_office'}, _('Client Action / Open'), planned),
                (_('Reservations'), {'front_office'}, _('Model CRUD / Workflow'), planned),
                (_('In-House Guests'), {'front_office'}, _('Read / Open'), planned),
                (_('Active Desk Folios'), {'front_office'}, _('Model CRUD / Workflow'), planned),
                (_('Group Blocks'), {'front_office'}, _('Model CRUD / Workflow'), planned),
                (_('Guest Database'), {'front_office'}, _('Model CRUD'), planned),
                (_('Guest Requests'), {'front_office'}, _('Read / Submit'), _('Manual Read and Submit are editable now. Submit uses a safe wizard; Edit/Delete remain planned.')),
                (_('Guest Chat Logs'), {'front_office'}, _('Read / Execute'), planned),
                (_('Run Night Audit'), {'night_auditor'}, _('Execute'), _('Planned / Not editable yet. Execution remains Night Auditor controlled.')),
                (_('Express QR Check-In'), {'front_office'}, _('Execute'), planned),
            ]),
            (_('Housekeeping'), [
                (_('Housekeeping Operations / List'), {'housekeeper'}, _('Model CRUD / Workflow'), planned),
                (_('Room Blocks'), {'front_office'}, _('Model CRUD / Workflow'), _('Planned / Not editable yet. Current menu/action behavior is unchanged.')),
                (_('Housekeeping Task Log'), {'housekeeper'}, _('Model CRUD / Workflow'), planned),
                (_('Maintenance Requests'), {'housekeeper'}, _('Model CRUD'), planned),
                (_('Housekeeping Status'), {'housekeeper'}, _('Execute'), _('Planned / Not editable yet. Room status methods remain guarded by existing logic.')),
                (_('Lost & Found'), {'housekeeper'}, _('Model CRUD'), _('Editable now through existing Lost & Found feature groups.')),
                (_('Supervisor Inspection'), {'housekeeping_supervisor'}, _('Execute / Workflow'), planned),
                (_('Minibar Post'), {'housekeeper'}, _('Execute'), planned),
                (_('Reservation Review'), {'housekeeper'}, _('Read-only / Open'), planned),
                (_('Today Arrivals'), {'housekeeper'}, _('Read-only / Open'), planned),
                (_('Stayover / In-House Guests'), {'housekeeper'}, _('Read-only / Open'), planned),
                (_('Today Departures'), {'housekeeper'}, _('Read-only / Open'), planned),
            ]),
            (_('Journal'), [
                (_('Master Posting Journal'), {'front_office', 'account_receivable'}, _('Read / Audit'), planned),
                (_('Change Journal'), {'front_office', 'account_receivable'}, _('Read / Audit'), planned),
                (_('Payment & Receipts'), {'front_office', 'account_receivable'}, _('Accounting-facing / Open'), planned),
                (_('Customer Invoices'), {'front_office'}, _('Accounting-facing / Open / Execute'), planned),
                (_('Tax Audit Folios'), {'night_auditor', 'account_receivable'}, _('Read / Audit'), planned),
                (_('Invoice Tax Audit'), {'night_auditor', 'account_receivable'}, _('Read / Audit'), planned),
            ]),
            (_('City Ledger'), [
                (_('Unpaid Folios / A/R'), {'account_receivable'}, _('Accounting-facing / Open'), planned),
                (_('Corporate Accounts'), {'account_receivable'}, _('Model CRUD / Open'), planned),
            ]),
            (_('Reporting'), [
                (_('Manager Daily Report'), {'night_auditor'}, _('Report / Open'), planned),
                (_('Revenue Analysis'), {'night_auditor'}, _('Report / Open'), planned),
                (_('Occupancy Analysis'), {'night_auditor'}, _('Report / Open'), planned),
                (_('Expected Arrivals'), {'night_auditor'}, _('Report / Execute'), planned),
                (_('Expected Departures'), {'night_auditor'}, _('Report / Execute'), planned),
                (_('Print Invoice and Receipt'), {'night_auditor'}, _('Report / Execute'), planned),
                (_('Daily Occupancy & Revenue'), {'night_auditor'}, _('Report / Open'), planned),
            ]),
            (_('Configuration'), [
                (_('Rate Plans'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Room Settings'), {'hotel_manager'}, _('Configuration Open'), planned),
                (_('Buildings / Zones'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Floors'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Room Types'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Rooms'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Amenities'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Pricing'), {'hotel_manager'}, _('Configuration Open'), planned),
                (_('Booking Sources'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Market Segments'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Guest Classifications'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Guest Analysis Dropdowns'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Products & Services'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Document Sequences'), {'hotel_manager'}, _('Configuration / Sequence'), planned),
                (_('Invoice & Receipt Sequences'), {'hotel_manager'}, _('Accounting-facing Configuration'), planned),
                (_('Setting Options'), {'hotel_manager'}, _('Configuration'), planned),
                (_('Setup Default Hotel Accounting'), {'hotel_manager', 'accounting_manager', 'odoo_system'}, _('High-risk Execute'), _('Restricted. Planned display only.')),
                (_('Document Templates'), {'hotel_manager'}, _('Configuration CRUD'), planned),
                (_('Backup & Restore'), {'odoo_system'}, _('System Admin'), _('Restricted. Planned display only.')),
                (_('Duplicate Guest Review'), {'odoo_system'}, _('System Cleanup'), _('Restricted. Planned display only.')),
            ]),
        ]

    def _hotel_feature_active_role_labels(self):
        self.ensure_one()
        role_specs = self._hotel_feature_role_specs()
        all_groups = self.all_group_ids
        active = {}
        for key, (label, xmlid) in role_specs.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and group in all_groups:
                active[key] = label
        return active

    @api.model
    def _hotel_feature_role_display_order(self):
        return [
            'odoo_system',
            'hotel_system_admin',
            'hotel_manager',
            'front_office_manager',
            'night_auditor',
            'housekeeping_manager',
            'housekeeping_supervisor',
            'housekeeping_user',
            'front_office',
            'account_receivable',
            'housekeeper',
            'accounting_manager',
        ]

    def _hotel_group_implies_group(self, source_group, target_group, seen=None):
        if not source_group or not target_group:
            return False
        if source_group == target_group:
            return True
        seen = seen or self.env['res.groups']
        if source_group in seen:
            return False
        seen |= source_group
        for implied_group in source_group.implied_ids:
            if self._hotel_group_implies_group(implied_group, target_group, seen):
                return True
        return False

    def _hotel_feature_inherited_access_summary(self, role_keys):
        self.ensure_one()
        role_specs = self._hotel_feature_role_specs()
        explicit_groups = self.group_ids
        effective_groups = self.all_group_ids
        labels = []

        ordered_role_keys = [
            key for key in self._hotel_feature_role_display_order()
            if key in role_keys
        ] + [
            key for key in role_keys
            if key not in self._hotel_feature_role_display_order()
        ]

        for role_key in ordered_role_keys:
            role_spec = role_specs.get(role_key)
            if not role_spec:
                continue

            role_label, role_xmlid = role_spec
            role_group = self.env.ref(role_xmlid, raise_if_not_found=False)
            if not role_group or role_group not in effective_groups:
                continue

            if role_group in explicit_groups:
                labels.append(str(role_label))
                continue

            provider_label = False
            for provider_key in self._hotel_feature_role_display_order():
                provider_spec = role_specs.get(provider_key)
                if not provider_spec:
                    continue
                provider_name, provider_xmlid = provider_spec
                provider_group = self.env.ref(provider_xmlid, raise_if_not_found=False)
                if (
                    provider_group
                    and provider_group in explicit_groups
                    and self._hotel_group_implies_group(provider_group, role_group)
                ):
                    provider_label = provider_name
                    break

            if provider_label:
                labels.append(_('%(provider)s via %(role)s') % {
                    'provider': provider_label,
                    'role': role_label,
                })
            else:
                labels.append(str(role_label))

        deduped = []
        for label in labels:
            if label not in deduped:
                deduped.append(label)
        return deduped

    def _hotel_lost_found_manual_access_summary(self):
        self.ensure_one()
        access = []
        if self.hotel_feature_lost_found_read:
            access.append(_('Read'))
        if self.hotel_feature_lost_found_create:
            access.append(_('Create'))
        if self.hotel_feature_lost_found_write:
            access.append(_('Edit'))
        if self.hotel_feature_lost_found_delete:
            access.append(_('Delete'))
        return ', '.join(access) if access else _('None')

    def _hotel_guest_request_manual_access_summary(self):
        self.ensure_one()
        access = []
        if self.hotel_feature_guest_request_read:
            access.append(_('Read'))
        if self.hotel_feature_guest_request_create:
            access.append(_('Submit'))
        return ', '.join(access) if access else _('None')

    def _hotel_feature_render_matrix_html(self):
        self.ensure_one()
        specs = self._hotel_feature_matrix_specs()

        html = [
            '<div class="o_hotel_feature_access_matrix">',
            '<p class="text-muted mb-3">',
            escape(str(_('Role Inherited Access is derived from the selected Hotel Roles. Manual Extra Access is editable for Lost & Found, and Guest Requests Read/Submit only in this phase.'))),
            '</p>',
        ]
        for section, features in specs:
            html.extend([
                '<h4 class="mt-3 mb-2">',
                escape(str(section)),
                '</h4>',
                '<table class="table table-sm table-bordered o_list_table mb-4">',
                '<thead><tr>',
                '<th>',
                escape(str(_('Feature'))),
                '</th><th>',
                escape(str(_('Role Inherited Access'))),
                '</th><th>',
                escape(str(_('Manual Extra Access'))),
                '</th><th>',
                escape(str(_('Effective Access'))),
                '</th><th>',
                escape(str(_('Access Type'))),
                '</th><th>',
                escape(str(_('Status / Notes'))),
                '</th>',
                '</tr></thead><tbody>',
            ])
            for feature_name, role_keys, access_type, note in features:
                inherited_labels = self._hotel_feature_inherited_access_summary(role_keys)
                inherited = ', '.join(inherited_labels) if inherited_labels else _('None')
                is_lost_found = feature_name == _('Lost & Found')
                is_guest_requests = feature_name == _('Guest Requests')
                if is_lost_found:
                    manual = self._hotel_lost_found_manual_access_summary()
                elif is_guest_requests:
                    manual = self._hotel_guest_request_manual_access_summary()
                else:
                    manual = _('Planned / Not editable yet')
                if inherited_labels and (is_lost_found or is_guest_requests) and manual != _('None'):
                    effective = _('Inherited + manual extra access')
                elif inherited_labels:
                    effective = _('Inherited from role')
                elif (is_lost_found or is_guest_requests) and manual != _('None'):
                    effective = _('Manual extra access')
                else:
                    effective = _('No effective feature access')

                html.extend([
                    '<tr>',
                    '<td>', escape(str(feature_name)), '</td>',
                    '<td>', escape(str(inherited)), '</td>',
                    '<td>', escape(str(manual)), '</td>',
                    '<td>', escape(str(effective)), '</td>',
                    '<td>', escape(str(access_type)), '</td>',
                    '<td>', escape(str(note)), '</td>',
                    '</tr>',
                ])
            html.append('</tbody></table>')
        html.append('</div>')
        return ''.join(html)

    @api.depends(
        'group_ids',
        'hotel_feature_lost_found_read',
        'hotel_feature_lost_found_create',
        'hotel_feature_lost_found_write',
        'hotel_feature_lost_found_delete',
        'hotel_feature_guest_request_read',
        'hotel_feature_guest_request_create',
        'hotel_feature_guest_request_write',
        'hotel_feature_guest_request_delete',
    )
    def _compute_hotel_feature_access_matrix_html(self):
        for user in self:
            user.hotel_feature_access_matrix_html = user._hotel_feature_render_matrix_html()

    @api.depends('group_ids')
    def _compute_hotel_feature_lost_found_access(self):
        groups_by_key = self._hotel_lost_found_feature_groups()
        feature_groups = self.env['res.groups'].browse([group.id for group in groups_by_key.values()])
        for user in self:
            explicit_groups = user.group_ids
            user.hotel_feature_lost_found_read = bool(explicit_groups & feature_groups)
            create_group = groups_by_key.get('create')
            write_group = groups_by_key.get('write')
            delete_group = groups_by_key.get('delete')
            user.hotel_feature_lost_found_create = bool(create_group and create_group in explicit_groups)
            user.hotel_feature_lost_found_write = bool(write_group and write_group in explicit_groups)
            user.hotel_feature_lost_found_delete = bool(delete_group and delete_group in explicit_groups)

    def _inverse_hotel_feature_lost_found_access(self):
        self._check_hotel_role_assignment_access()
        groups_by_key = self._hotel_lost_found_feature_groups()
        feature_groups = self.env['res.groups'].browse([group.id for group in groups_by_key.values()])

        for user in self:
            read = bool(user.hotel_feature_lost_found_read)
            create = bool(user.hotel_feature_lost_found_create)
            write = bool(user.hotel_feature_lost_found_write)
            delete = bool(user.hotel_feature_lost_found_delete)

            if create or write or delete:
                read = True
            if not read:
                create = write = delete = False

            selected_groups = self.env['res.groups']
            for key, selected in {
                'read': read,
                'create': create,
                'write': write,
                'delete': delete,
            }.items():
                if selected and groups_by_key.get(key):
                    selected_groups |= groups_by_key[key]

            commands = [(3, group.id, 0) for group in feature_groups]
            commands += [(4, group.id, 0) for group in selected_groups]
            user.sudo().write({'group_ids': commands})

    @api.onchange(
        'hotel_feature_lost_found_read',
        'hotel_feature_lost_found_create',
        'hotel_feature_lost_found_write',
        'hotel_feature_lost_found_delete',
    )
    def _onchange_hotel_feature_lost_found_access(self):
        self._onchange_hotel_feature_dependency(
            'hotel_feature_lost_found_read',
            'hotel_feature_lost_found_create',
            'hotel_feature_lost_found_write',
            'hotel_feature_lost_found_delete',
        )

    @api.depends('group_ids')
    def _compute_hotel_feature_guest_request_access(self):
        groups_by_key = self._hotel_guest_request_feature_groups()
        feature_groups = self.env['res.groups'].browse([group.id for group in groups_by_key.values()])
        legacy_raw_groups = self._hotel_guest_request_legacy_raw_groups()
        for user in self:
            explicit_groups = user.group_ids
            user.hotel_feature_guest_request_read = bool(explicit_groups & (feature_groups | legacy_raw_groups))
            create_group = groups_by_key.get('create')
            write_group = groups_by_key.get('write')
            delete_group = groups_by_key.get('delete')
            user.hotel_feature_guest_request_create = bool(create_group and create_group in explicit_groups)
            user.hotel_feature_guest_request_write = bool(write_group and write_group in explicit_groups)
            user.hotel_feature_guest_request_delete = bool(delete_group and delete_group in explicit_groups)

    def _inverse_hotel_feature_guest_request_access(self):
        self._check_hotel_role_assignment_access()
        groups_by_key = self._hotel_guest_request_feature_groups()
        feature_groups = self.env['res.groups'].browse([group.id for group in groups_by_key.values()])
        legacy_raw_groups = self._hotel_guest_request_legacy_raw_groups()
        removable_groups = feature_groups | legacy_raw_groups

        for user in self:
            read = bool(user.hotel_feature_guest_request_read or user.hotel_feature_guest_request_create)

            selected_groups = self.env['res.groups']
            if read and groups_by_key.get('read'):
                selected_groups |= groups_by_key['read']
            if user.hotel_feature_guest_request_create and groups_by_key.get('create'):
                selected_groups |= groups_by_key['create']

            commands = [(3, group.id, 0) for group in removable_groups]
            commands += [(4, group.id, 0) for group in selected_groups]
            user.sudo().write({'group_ids': commands})

    @api.onchange(
        'hotel_feature_guest_request_read',
        'hotel_feature_guest_request_create',
    )
    def _onchange_hotel_feature_guest_request_access(self):
        for user in self:
            if user.hotel_feature_guest_request_create:
                user.hotel_feature_guest_request_read = True
            if not user.hotel_feature_guest_request_read:
                user.hotel_feature_guest_request_create = False
                user.hotel_feature_guest_request_write = False
                user.hotel_feature_guest_request_delete = False

    def _onchange_hotel_feature_dependency(self, read_field, create_field, write_field, delete_field):
        for user in self:
            read = bool(user[read_field])
            has_child_access = bool(user[create_field] or user[write_field] or user[delete_field])
            had_read = bool(user._origin and user._origin[read_field])

            if had_read and not read:
                user[create_field] = False
                user[write_field] = False
                user[delete_field] = False
            elif has_child_access:
                user[read_field] = True

    def _hotel_role_labels_from_groups(self, groups):
        labels = []
        for _key, label, xmlid in self._hotel_role_group_specs():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group and group in groups:
                labels.append(label)
        return labels

    @api.depends('group_ids')
    def _compute_hotel_effective_role_summary(self):
        for user in self:
            labels = user._hotel_role_labels_from_groups(user.all_group_ids)
            user.hotel_effective_role_summary = "\n".join(labels) if labels else _("No hotel operational roles assigned.")

    def action_open_hotel_role_assignment_wizard(self):
        self.ensure_one()
        self._check_hotel_role_assignment_access()
        view = self.env.ref('hotel_management.view_hotel_role_assignment_wizard_form')
        return {
            'name': _('Assign Hotel Roles'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.role.assignment.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_user_id': self.id,
                'active_model': 'res.users',
                'active_id': self.id,
            },
        }
