from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HotelQuickAccessItem(models.Model):
    _name = 'hotel.quick.access.item'
    _description = 'Hotel Quick Access Toolbar Item'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help="Leave empty to show for all companies.",
    )

    action_type = fields.Selection(
        [
            ('action', 'Odoo Action'),
            ('menu', 'Odoo Menu'),
            ('url', 'URL'),
        ],
        string='Action Type',
        required=True,
        default='action',
    )

    action_id = fields.Many2one(
        'ir.actions.act_window',
        string='Window Action',
        help="Select an existing Odoo window action.",
    )

    menu_id = fields.Many2one(
        'ir.ui.menu',
        string='Menu',
        help="Select an existing Odoo menu. The menu action will be opened.",
    )

    url = fields.Char(
        string='URL',
        help="Example: /odoo/action-123 or https://example.com",
    )

    icon_type = fields.Selection(
        [
            ('fa', 'Font Awesome'),
            ('image', 'Uploaded Image'),
        ],
        string='Icon Type',
        default='fa',
        required=True,
    )

    icon_class = fields.Char(
        string='Font Awesome Icon',
        default='fa-star',
        help="Example: fa-calendar, fa-bed, fa-users, fa-money",
    )

    icon_image = fields.Binary(
        string='Icon Image',
        attachment=True,
        help="Upload PNG/JPG/WebP icon. Recommended size: 24x24 or 32x32.",
    )

    button_color = fields.Selection(
        [
            ('primary', 'Blue'),
            ('success', 'Green'),
            ('warning', 'Yellow'),
            ('danger', 'Red'),
            ('info', 'Cyan'),
            ('secondary', 'Gray'),
            ('dark', 'Dark'),
        ],
        string='Button Color',
        default='primary',
        required=True,
    )

    button_css_class = fields.Char(
        compute='_compute_button_css_class',
        string='Button CSS Class',
    )

    group_ids = fields.Many2many(
        'res.groups',
        string='Visible For Groups',
        help="Leave empty to show to all internal users.",
    )

    open_type = fields.Selection(
        [
            ('current', 'Current Window'),
            ('new', 'New Window / Modal'),
        ],
        string='Open Type',
        default='current',
        required=True,
    )

    @api.depends('button_color')
    def _compute_button_css_class(self):
        for rec in self:
            rec.button_css_class = 'btn-%s' % (rec.button_color or 'primary')

    def _is_visible_for_user(self):
        self.ensure_one()

        if not self.active:
            return False

        if self.company_id and self.company_id != self.env.company:
            return False

        if not self.group_ids:
            return True

        user_groups = self.env.user.all_group_ids
        return bool(self.group_ids & user_groups)

    def action_open(self):
        self.ensure_one()

        if not self._is_visible_for_user() and not self.env.user.has_group('base.group_system'):
            raise UserError(_("You do not have access to this quick access item."))

        if self.action_type == 'action':
            if not self.action_id:
                raise UserError(_("Please select an Odoo Action."))
            action = self.action_id.sudo().read()[0]
            action['target'] = 'new' if self.open_type == 'new' else 'current'
            return action

        if self.action_type == 'menu':
            if not self.menu_id:
                raise UserError(_("Please select an Odoo Menu."))
            if not self.menu_id.action:
                raise UserError(_("The selected menu does not have an action."))
            action = self.menu_id.action.sudo().read()[0]
            action['target'] = 'new' if self.open_type == 'new' else 'current'
            return action

        if self.action_type == 'url':
            if not self.url:
                raise UserError(_("Please enter a URL."))
            return {
                'type': 'ir.actions.act_url',
                'url': self.url,
                'target': 'new' if self.open_type == 'new' else 'self',
            }

        raise UserError(_("Invalid quick access action type."))

    @api.model
    def _qa_groups(self, xmlids):
        groups = self.env['res.groups'].sudo()
        for xmlid in xmlids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                groups |= group
        return groups

    @api.model
    def _qa_model_exists(self, model_name):
        return bool(self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1))

    @api.model
    def _qa_get_or_create_action(self, name, res_model, view_mode='list,form', domain=None, context=None, target='current'):
        if not self._qa_model_exists(res_model):
            return False

        Action = self.env['ir.actions.act_window'].sudo()

        action = Action.search([
            ('name', '=', name),
            ('res_model', '=', res_model),
        ], limit=1)

        vals = {
            'name': name,
            'res_model': res_model,
            'view_mode': view_mode,
            'domain': str(domain or []),
            'context': str(context or {}),
            'target': target,
        }

        if action:
            action.write(vals)
        else:
            action = Action.create(vals)

        return action

    @api.model
    def _qa_find_action_by_name(self, names, res_model=False):
        Action = self.env['ir.actions.act_window'].sudo()
        for name in names:
            domain = [('name', 'ilike', name)]
            if res_model:
                domain.append(('res_model', '=', res_model))
            action = Action.search(domain, limit=1)
            if action:
                return action
        return False

    @api.model        
    def _qa_create_item_if_missing(
        self,
        name,
        sequence,
        action=False,
        menu=False,
        icon_class='fa-star',
        button_color='primary',
        open_type='current',
        group_xmlids=None,
        force_update=False,
    ):
        Item = self.sudo()
        item = Item.search([('name', '=', name)], limit=1)

        groups = self._qa_groups(group_xmlids or [])

        vals = {
            'active': True,
            'sequence': sequence,
            'company_id': False,
            'icon_type': 'fa',
            'icon_class': icon_class,
            'button_color': button_color,
            'open_type': open_type,
        }

        if menu:
            vals.update({
                'action_type': 'menu',
                'menu_id': menu.id,
                'action_id': False,
                'url': False,
            })
        elif action:
            vals.update({
                'action_type': 'action',
                'action_id': action.id,
                'menu_id': False,
                'url': False,
            })
        else:
            return False

        if groups:
            vals['group_ids'] = [(6, 0, groups.ids)]

        if item:
            if force_update:
                item.write(vals)
            elif not item.action_id and not item.menu_id:
                item.write(vals)
            return item

        vals['name'] = name
        return Item.create(vals)

    @api.model
    def _qa_find_menu_by_name(self, names):
        Menu = self.env['ir.ui.menu'].sudo()

        for name in names:
            menus = Menu.search([
                ('name', 'ilike', name),
                ('action', '!=', False),
            ], order='sequence, id')

            hotel_menus = menus.filtered(
                lambda menu: 'Hotel' in (menu.complete_name or '')
            )
            if hotel_menus:
                return hotel_menus[0]

            if menus:
                return menus[0]

        return False

    @api.model
    def create_default_quick_access_items(self):
        front_office_groups = [
            'hotel_management.group_hotel_front_office',
            'hotel_management.group_hotel_front_office_manager',
            'hotel_management.group_hotel_manager',
            'hotel_management.group_hotel_system_admin',
            'base.group_system',
        ]

        # 1. Express QR Check-In
        express_action = self._qa_find_action_by_name(
            ['Express QR Check-In', 'QR Check-In', 'Express Check-In', 'Pre-Arrival QR'],
            res_model=False,
        )
        if not express_action:
            express_action = self._qa_get_or_create_action(
                name='QA - Express QR Check-In',
                res_model='hotel.express.checkin.wizard',
                view_mode='form',
                domain=[],
                context={},
                target='new',
            )
        self._qa_create_item_if_missing(
            name='Express QR Check-In',
            sequence=5,
            action=express_action,
            icon_class='fa-qrcode',
            button_color='success',
            open_type='new',
            group_xmlids=front_office_groups,
        )

        # 2. Reservations
        reservations_action = self._qa_get_or_create_action(
            name='QA - Reservations',
            res_model='hotel.reservation',
            view_mode='list,form',
            domain=[
                ('is_desk_folio', '=', False),
                ('state', 'not in', ['cancel', 'blocked']),
            ],
            context={'create': True},
        )
        self._qa_create_item_if_missing(
            name='Reservations',
            sequence=10,
            action=reservations_action,
            icon_class='fa-calendar',
            button_color='primary',
            group_xmlids=front_office_groups,
        )

        # 3. In-House Guests
        inhouse_action = self._qa_get_or_create_action(
            name='QA - In-House Guests',
            res_model='hotel.reservation',
            view_mode='list,form',
            domain=[
                ('is_desk_folio', '=', False),
                ('state', 'in', ['checkin', 'checkout_hold']),
            ],
            context={'create': False},
        )
        self._qa_create_item_if_missing(
            name='In-House Guests',
            sequence=20,
            action=inhouse_action,
            icon_class='fa-bed',
            button_color='info',
            group_xmlids=front_office_groups,
        )

        # 4. Room Chart
        room_chart_menu = self._qa_find_menu_by_name([
            'Room Chart',
            'Tape Chart',
            'Room Rack',
        ])

        self._qa_create_item_if_missing(
            name='Room Chart',
            sequence=30,
            menu=room_chart_menu,
            icon_class='fa-th',
            button_color='warning',
            group_xmlids=front_office_groups,
            force_update=True,
        )

        # 5. Availability
        availability_menu = self._qa_find_menu_by_name([
            'Availability',
            'Room Availability',
            'Availability Report',
        ])

        self._qa_create_item_if_missing(
            name='Availability',
            sequence=40,
            menu=availability_menu,
            icon_class='fa-search',
            button_color='secondary',
            group_xmlids=front_office_groups,
            force_update=True,
        )

        return True

class HotelDashboardQuickAccess(models.Model):
    _inherit = 'hotel.dashboard'

    quick_access_item_ids = fields.Many2many(
        'hotel.quick.access.item',
        compute='_compute_quick_access_item_ids',
        string='Quick Access Items',
    )

    def _compute_quick_access_item_ids(self):
        Item = self.env['hotel.quick.access.item'].sudo()

        for dashboard in self:
            items = Item.search([
                ('active', '=', True),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.env.company.id),
            ])

            visible_items = items.filtered(lambda item: item.with_user(self.env.user)._is_visible_for_user())
            dashboard.quick_access_item_ids = visible_items

    def action_open_quick_access_setup(self):
        return {
            'name': _('Quick Access Toolbar Setup'),
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.quick.access.item',
            'view_mode': 'list,form',
            'target': 'current',
            'context': {'create': True},
        }