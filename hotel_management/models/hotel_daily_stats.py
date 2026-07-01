from odoo import models, fields, api, _
from datetime import timedelta

class HotelDailyStats(models.Model):
    _name = 'hotel.daily.stats'
    _description = 'Hotel Daily Statistics'
    _order = 'date'

    date = fields.Date(string='Date', required=True, index=True)
    
    # --- Raw Stored Stats (Calculated nightly) ---
    occupancy_pc = fields.Float(string='Occupancy %')
    adr = fields.Float(string='ADR (Average Daily Rate)')
    revpar = fields.Float(string='RevPAR (Revenue Per Available Room)')
    
    # --- FIX: Added Missing Field ---
    total_revenue = fields.Float(string='Total Revenue')
    
    # --- Dynamic Display Fields (Computed on-the-fly) ---
    display_value = fields.Char(compute='_compute_display_fields')
    color_index = fields.Integer(compute='_compute_display_fields')

    _date_unique = models.Constraint(
        'UNIQUE(date)',
        'Statistics for this date already exist.',
    )

    @api.depends('occupancy_pc', 'adr', 'revpar', 'total_revenue')
    def _compute_display_fields(self):
        # Read the context to see which metric the user wants to see
        metric = self.env.context.get('metric_to_show', 'occupancy')
        
        for rec in self:
            if metric == 'occupancy':
                rec.display_value = f"{rec.occupancy_pc:.0f}%"
                if rec.occupancy_pc >= 90: rec.color_index = 1   # Red
                elif rec.occupancy_pc >= 70: rec.color_index = 2 # Yellow
                elif rec.occupancy_pc >= 50: rec.color_index = 3 # Blue
                else: rec.color_index = 4                        # Green
            
            elif metric == 'adr':
                rec.display_value = f"${rec.adr:.2f}"
                if rec.adr >= 200: rec.color_index = 1
                elif rec.adr >= 150: rec.color_index = 2
                else: rec.color_index = 4
            
            elif metric == 'revpar':
                rec.display_value = f"${rec.revpar:.2f}"
                if rec.revpar >= 180: rec.color_index = 1
                elif rec.revpar >= 120: rec.color_index = 2
                else: rec.color_index = 4

            elif metric == 'total_revenue':
                rec.display_value = f"${rec.total_revenue:,.0f}"
                if rec.total_revenue > 0: rec.color_index = 3 # Blue for any revenue
                else: rec.color_index = 0
            
            else:
                rec.display_value = ""
                rec.color_index = 0

    # =========================================================
    #  CALCULATION LOGIC (Run by Cron Job)
    # =========================================================
    @api.model
    def cron_calculate_daily_stats(self):
        """Calculates stats for today and the next 365 days."""
        today = fields.Date.today()
        # Calculate for yesterday too, to ensure past data is filled
        yesterday = today - timedelta(days=1)
        
        # Range: Yesterday + Next 365 days
        for i in range(-1, 366): 
            target_date = today + timedelta(days=i)
            self._calculate_stats_for_date(target_date)

    @api.model
    def _calculate_stats_for_date(self, target_date):
        # 1. Total Rooms
        total_rooms = self.env['hotel.room'].search_count([])
        if total_rooms == 0: return

        # 2. Unavailable (Blocked) Rooms
        blocked_domain = [('state', '=', 'blocked'), ('checkin_date', '<=', target_date), ('checkout_date', '>', target_date)]
        legacy_blocked_count = self.env['hotel.reservation'].search_count(blocked_domain)
        room_blocked_count = self.env['hotel.room.block'].sudo().search_count([
            ('state', '=', 'active'),
            ('date_from', '<=', target_date),
            ('date_to', '>', target_date),
        ])
        blocked_count = legacy_blocked_count + room_blocked_count
        available_rooms = total_rooms - blocked_count

        # 3. Actual occupied rooms & folio-based revenue for this business date
        daily_rows = self.env['hotel.revenue.report'].search([
            ('date', '=', target_date),
            ('revenue_type', '=', 'actual'),
        ])
        occupied_count = sum(daily_rows.mapped('occupied_count'))
        daily_revenue = sum(daily_rows.mapped('folio_total'))

        # 4. Calculate Metrics
        occupancy_pc = (occupied_count / total_rooms * 100) if total_rooms > 0 else 0.0
        adr = (daily_revenue / occupied_count) if occupied_count > 0 else 0.0
        revpar = (daily_revenue / total_rooms) if total_rooms > 0 else 0.0

        # 5. Store Results (INCLUDES total_revenue)
        vals = {
            'occupancy_pc': occupancy_pc, 
            'adr': adr, 
            'revpar': revpar, 
            'total_revenue': daily_revenue # <--- Saving the missing field
        }
        
        stats_rec = self.search([('date', '=', target_date)], limit=1)
        if stats_rec: 
            stats_rec.write(vals)
        else:
            vals['date'] = target_date
            self.create(vals)
