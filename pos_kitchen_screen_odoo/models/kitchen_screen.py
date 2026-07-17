# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
############################################################################
from odoo import api, fields, models


class KitchenScreen(models.Model):
    """Kitchen Screen model for the cook"""
    _name = 'kitchen.screen'
    _description = 'Pos Kitchen Screen'
    _rec_name = 'sequence'

    def _pos_shop_id(self):
        """Domain for the Pos Shop"""
        kitchen = self.search([])
        if kitchen:
            return [('module_pos_restaurant', '=', True),
                    ('id', 'not in', kitchen.mapped('pos_config_id').ids)]
        else:
            return [('module_pos_restaurant', '=', True)]

    sequence = fields.Char(readonly=True, default='New',
                           copy=False, help="Sequence of items")
    pos_config_id = fields.Many2one('pos.config', string='Allowed POS',
                                    domain=_pos_shop_id,
                                    help="Allowed POS for kitchen")
    pos_categ_ids = fields.Many2many('pos.category',
                                     string='Allowed POS Category',
                                     help="Allowed POS Category"
                                          "for the corresponding Pos")
    shop_number = fields.Integer(related='pos_config_id.id', string='Customer',
                                 help="Id of the POS")

    is_preparation_complete = fields.Boolean(
        string='Change Stage',
        default=False,
        help='Change the cooking stage when completing the preparation time',
    )
    to_prepare_count = fields.Integer(
        string='To Prepare',
        compute='_compute_display_stats',
    )
    ready_count = fields.Integer(
        string='Ready',
        compute='_compute_display_stats',
    )
    completed_count = fields.Integer(
        string='Completed',
        compute='_compute_display_stats',
    )
    in_progress_count = fields.Integer(
        string='In Progress',
        compute='_compute_display_stats',
    )
    average_time_display = fields.Char(
        string='Average Time',
        compute='_compute_display_stats',
    )

    def kitchen_screen(self):
        """Redirect to corresponding kitchen screen for the cook"""
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': '/pos/kitchen?pos_config_id= %s' % self.pos_config_id.id,
        }

    def action_open_preparation_screen(self):
        """Open the kitchen preparation screen for this outlet."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'kitchen_custom_dashboard_tags',
            'target': 'fullscreen',
            'context': {'default_shop_id': self.pos_config_id.id},
        }

    def action_open_status_display(self):
        """Open the customer-facing order status display."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': '/pos/kitchen/status?pos_config_id=%s' % self.pos_config_id.id,
        }

    def _compute_display_stats(self):
        """Compute dashboard numbers for the outlet card."""
        PosOrder = self.env['pos.order'].sudo()
        for kitchen in self:
            orders = PosOrder.search([
                ('config_id', '=', kitchen.pos_config_id.id),
                ('is_cooking', '=', True),
                ('state', '!=', 'cancel'),
                ('order_status', 'in', ['draft', 'waiting', 'ready']),
            ]) if kitchen.pos_config_id else PosOrder.browse()
            to_prepare = orders.filtered(lambda order: order.order_status == 'draft')
            ready = orders.filtered(lambda order: order.order_status == 'waiting')
            completed = orders.filtered(lambda order: order.order_status == 'ready')
            in_progress = to_prepare | ready
            prepare_times = [
                order.avg_prepare_time
                for order in in_progress
                if order.avg_prepare_time
            ]
            average_time = sum(prepare_times) / len(prepare_times) if prepare_times else 0

            kitchen.to_prepare_count = len(to_prepare)
            kitchen.ready_count = len(ready)
            kitchen.completed_count = len(completed)
            kitchen.in_progress_count = len(in_progress)
            kitchen.average_time_display = "%s'" % int(round(average_time))

    @api.model_create_multi
    def create(self, vals_list):
        """Used to create sequence"""
        for vals in vals_list:
            if vals.get('sequence', "New") == "New":
                vals['sequence'] = self.env['ir.sequence'].next_by_code(
                    'kitchen.screen') or "New"
        return super().create(vals_list)
